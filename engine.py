"""Playwright testing engine.

Honest-by-design notes
- Bandwidth/latency are applied with Chromium's CDP `Network.emulateNetworkConditions` (browser-level
  emulation, NOT OS traffic control and NOT a real mobile network).
- CPU slowdown uses CDP `Emulation.setCPUThrottlingRate` (slows the renderer relative to THIS machine; it is not a
  physical low-end phone and says nothing about RAM, battery or thermal behaviour).
- Packet loss is *simulated* by aborting a seeded random share of non-document requests (fault injection). Real
  packet loss would be retransmitted by TCP; this is not that.
- If a requested constraint cannot be applied the run FAILS rather than silently running unconstrained.
- Pages can only reach the registered target origin; everything else is aborted and counted.
"""
import random
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from .security import is_request_allowed

_open_browsers = 0
_open_lock = threading.Lock()
LAST_BROWSER = None          # exposed for tests (cleanup verification)


def open_browser_count():
    return _open_browsers


class RunCancelled(Exception):
    pass


class EnforcementError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _kbps_to_bytes(kbps):
    return -1 if not kbps else int(kbps * 1000 / 8)


PAGE_METRICS_JS = """async () => {
  const lcpVal = await new Promise(res => {
    let v = null;
    try { new PerformanceObserver(l => { const e = l.getEntries(); if (e.length) v = e[e.length - 1].startTime; })
            .observe({type: 'largest-contentful-paint', buffered: true}); } catch (e) { return res(null); }
    setTimeout(() => res(v), 150);
  });
  const nav = performance.getEntriesByType('navigation')[0];
  const fcp = performance.getEntriesByName('first-contentful-paint')[0];
  const res = performance.getEntriesByType('resource');
  const sz = e => e.transferSize || e.encodedBodySize || 0;
  return {
    nav_duration_ms: nav ? nav.duration : null,
    dom_content_loaded_ms: nav ? nav.domContentLoadedEventEnd : null,
    load_ms: nav && nav.loadEventEnd > 0 ? nav.loadEventEnd : null,
    fcp_ms: fcp ? fcp.startTime : null,
    lcp_ms: lcpVal,
    resource_count: res.length + 1,
    transfer_bytes: (nav ? sz(nav) : 0) + res.reduce((a, e) => a + sz(e), 0)
  };
}"""

API_FETCH_JS = """async ({method, path, body}) => {
  const t0 = performance.now();
  const opts = {method, headers: {}};
  if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  await r.arrayBuffer();
  return {status: r.status, ms: performance.now() - t0};
}"""


class RepetitionRecorder:
    """Collects network + JS error events for one repetition (one fresh browser context)."""

    def __init__(self, origin):
        self.origin = origin
        self.step = None
        self.entries = []       # dicts keyed per request object
        self.by_req = {}
        self.js_errors = []
        self.blocked = []
        self.simulated = set()

    def attach(self, page):
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("requestfinished", self._on_finished)
        page.on("requestfailed", self._on_failed)
        page.on("pageerror", lambda e: self.js_errors.append({"step": self.step, "kind": "exception", "message": str(e)}))
        page.on("console", self._on_console)

    def _on_console(self, msg):
        if msg.type == "error" and not msg.text.startswith("Failed to load resource"):
            self.js_errors.append({"step": self.step, "kind": "console_error", "message": msg.text})

    def _on_request(self, req):
        e = {"req": req, "step": self.step, "status": None, "headers": {}, "state": "pending", "failure": None,
             "t_wall": time.perf_counter()}
        self.by_req[req] = e
        self.entries.append(e)

    def _on_response(self, resp):
        e = self.by_req.get(resp.request)
        if e:
            e["status"] = resp.status
            e["headers"] = {k.lower(): v for k, v in resp.headers.items()}

    def _on_finished(self, req):
        e = self.by_req.get(req)
        if e:
            e["state"] = "finished"

    def _on_failed(self, req):
        e = self.by_req.get(req)
        if e:
            e["state"] = "failed"
            e["failure"] = req.failure

    def collect(self, step_id):
        """Convert raw entries of `step_id` into DB-ready dicts. Called outside event handlers."""
        out, pending = [], []
        for e in [x for x in self.entries if x["step"] == step_id]:
            req = e["req"]
            u = urlparse(req.url)
            path = u.path + (("?" + u.query) if u.query else "")
            is_api = u.path.startswith("/api/") or req.resource_type in ("fetch", "xhr")
            base = {"method": req.method, "path": path[:300], "resource_type": req.resource_type, "is_api": is_api,
                    "status": e["status"], "source": "browser (Playwright)"}
            sm = e["headers"].get("x-server-time-ms")
            base["server_ms"] = float(sm) if sm and sm.replace(".", "", 1).isdigit() else None
            if e["state"] == "pending" and e["status"] is None:
                pending.append(f"{req.method} {u.path}")
                continue
            if e["state"] == "failed":
                sim = req in self.simulated
                base.update(failed=True, simulated_fault=sim, duration_ms=None, transfer_bytes=None,
                            failure_text="simulated packet loss (fault injection)" if sim else (e["failure"] or "network failure"))
                out.append(base)
                continue
            try:
                t = req.timing
                dur = t["responseEnd"] if t and t.get("responseEnd", -1) >= 0 else None
                if e["state"] == "finished":
                    s = req.sizes()
                    size = (s.get("responseBodySize") or 0) + (s.get("responseHeadersSize") or 0)
                else:  # response seen but no 'finished' event (e.g. some 5xx): avoid blocking, use Content-Length
                    cl = e["headers"].get("content-length", "")
                    size = int(cl) if cl.isdigit() else None
            except PWError:
                dur, size = None, None
            http_fail = (e["status"] or 0) >= 400
            base.update(failed=http_fail, simulated_fault=False, duration_ms=dur, transfer_bytes=size,
                        failure_text=f"HTTP {e['status']}" if http_fail else None)
            out.append(base)
        return out, pending


def _enforce(context, page, profile, requested_only=False):
    """Apply network/CPU constraints. Returns list of enforcement records. Raises EnforcementError on failure."""
    records = []
    dl, ul, lat = profile.get("download_kbps"), profile.get("upload_kbps"), profile.get("latency_ms") or 0
    cpu = profile.get("cpu_slowdown") or 1
    loss = profile.get("packet_loss_pct") or 0
    shaped = bool(dl or ul or lat)
    cdp = None
    if shaped or cpu > 1:
        try:
            cdp = context.new_cdp_session(page)
            cdp.send("Network.enable")
            if shaped:
                cdp.send("Network.emulateNetworkConditions", {
                    "offline": False, "latency": lat,
                    "downloadThroughput": _kbps_to_bytes(dl), "uploadThroughput": _kbps_to_bytes(ul)})
            if cpu > 1:
                cdp.send("Emulation.setCPUThrottlingRate", {"rate": cpu})
        except PWError as e:
            raise EnforcementError(f"Could not apply requested constraints via CDP: {e}")
    net_method = "Chromium CDP Network.emulateNetworkConditions (browser-level emulation, not OS traffic control)"
    records.append({"setting": "download_kbps", "requested": dl, "status": "applied" if dl else "not_requested", "method": net_method if dl else None})
    records.append({"setting": "upload_kbps", "requested": ul, "status": "applied" if ul else "not_requested", "method": net_method if ul else None})
    records.append({"setting": "latency_ms", "requested": lat, "status": "applied" if lat else "not_requested", "method": net_method if lat else None})
    records.append({"setting": "cpu_slowdown", "requested": cpu, "status": "applied" if cpu > 1 else "not_requested",
                    "method": "Chromium CDP Emulation.setCPUThrottlingRate (renderer slowdown relative to this host; not a physical device)" if cpu > 1 else None})
    records.append({"setting": "packet_loss_pct", "requested": loss, "status": "simulated" if loss else "not_requested",
                    "method": "Request-level fault injection: seeded random abort of non-document requests (NOT real packet loss)" if loss else None})
    return records


def _verify(enforcement, all_requests):
    """Compare observed behaviour with requested shaping and annotate records (best-effort, honest)."""
    for rec in enforcement:
        if rec["status"] != "applied":
            continue
        if rec["setting"] == "download_kbps":
            big = [r for r in all_requests if r.get("transfer_bytes") and r["transfer_bytes"] >= 100_000 and r.get("duration_ms")]
            if not big:
                rec["verification"] = "not verifiable: no response >= 100 KB observed"
                continue
            obs = max(r["transfer_bytes"] * 8 / (r["duration_ms"] / 1000) / 1000 for r in big)
            rec["observed_max_kbps"] = round(obs, 1)
            rec["verification"] = "consistent: observed throughput <= 1.35x requested" if obs <= rec["requested"] * 1.35 \
                else "INCONSISTENT: observed throughput exceeds requested limit"
        elif rec["setting"] == "latency_ms":
            durs = [r["duration_ms"] for r in all_requests if r.get("duration_ms") and not r["failed"]]
            if not durs:
                rec["verification"] = "not verifiable: no completed requests"
                continue
            rec["observed_min_request_ms"] = round(min(durs), 1)
            rec["verification"] = "consistent: no request finished faster than 0.8x requested latency" if min(durs) >= rec["requested"] * 0.8 \
                else "INCONSISTENT: some requests completed faster than the requested latency"


def _wait_and_measure(page, step, timeout):
    if step.get("wait_selector"):
        page.wait_for_selector(step["wait_selector"], timeout=timeout)


def _run_step(page, origin, step, timeout, holder):
    """Execute one declarative step. Returns optional page-metric dict."""
    t = step.get("type")
    url = lambda p: origin.rstrip("/") + p
    metrics = None
    if t == "navigate":
        resp = page.goto(url(step["path"]), wait_until="load", timeout=timeout)
        if resp is None or resp.status >= 400:
            raise PWError(f"Navigation returned HTTP {resp.status if resp else 'no response'}")
        _wait_and_measure(page, step, timeout)
        if step.get("measure_page", True):
            metrics = page.evaluate(PAGE_METRICS_JS)
    elif t in ("form", "click_wait"):
        resp = page.goto(url(step["path"]), wait_until="load", timeout=timeout)
        if resp is None or resp.status >= 400:
            raise PWError(f"Navigation returned HTTP {resp.status if resp else 'no response'}")
        metrics = page.evaluate(PAGE_METRICS_JS)
        metrics["path"] = step.get("path"); metrics["source"] = "browser (Navigation/Paint Timing API)"
        holder["metrics"] = metrics      # keep load metrics even if a later action in the step fails
        for sel, val in (step.get("fill") or {}).items():
            page.fill(sel, val, timeout=timeout)
        page.click(step["click"], timeout=timeout)
        _wait_and_measure(page, step, timeout)
    elif t == "api":
        r = page.evaluate(API_FETCH_JS, {"method": step["method"], "path": step["path"], "body": step.get("body")})
        if step.get("require_ok") and r["status"] >= 400:
            raise PWError(f"API returned HTTP {r['status']}")
    else:
        raise ValueError(f"Unknown step type {t}")
    if metrics:
        metrics["path"] = step.get("path")
        metrics["source"] = "browser (Navigation/Paint Timing API)"
        holder["metrics"] = metrics


def run_workflow(*, origin, profile, workflow, repetitions, seed, sink, on_event, should_cancel, headless=True,
                 max_run_seconds=600):
    """Run `workflow` `repetitions` times, each in a fresh browser context.

    `sink` must provide add_step/add_requests/add_page_metric/add_js_errors (bound to a run id).
    Returns {"environment": {...}}.
    """
    global _open_browsers, LAST_BROWSER
    deadline = time.monotonic() + max_run_seconds
    all_requests, enforcement, blocked_total = [], [], 0
    step_timeout_default = int(profile.get("step_timeout_ms") or 15000)
    pw = browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=headless, args=["--disable-dev-shm-usage"])
        with _open_lock:
            _open_browsers += 1
        LAST_BROWSER = browser
        browser_version = browser.version
        steps = workflow["steps"]
        for rep in range(1, repetitions + 1):
            if should_cancel():
                raise RunCancelled()
            context = browser.new_context(viewport={"width": 412, "height": 915}, ignore_https_errors=False)
            try:
                page = context.new_page()
                rng = random.Random(seed * 1000 + rep)
                recorder = RepetitionRecorder(origin)

                def handler(route, request, recorder=recorder, rng=rng):
                    if not is_request_allowed(request.url, origin):
                        recorder.blocked.append(request.url)
                        return route.abort("blockedbyclient")
                    loss = profile.get("packet_loss_pct") or 0
                    if loss and request.resource_type != "document" and rng.random() * 100 < loss:
                        recorder.simulated.add(request)
                        return route.abort("connectionfailed")
                    return route.continue_()

                context.route("**/*", handler)
                recorder.attach(page)
                enf = _enforce(context, page, profile)
                if rep == 1:
                    enforcement = enf
                on_event(f"Repetition {rep}/{repetitions}: constraints applied" if any(r["status"] != "not_requested" for r in enf)
                         else f"Repetition {rep}/{repetitions}: no constraints requested (unmodified browser session)")
                for step in steps:
                    if should_cancel():
                        raise RunCancelled()
                    if time.monotonic() > deadline:
                        raise TimeoutError("Run exceeded maximum run time")
                    timeout = int(step.get("timeout_ms") or step_timeout_default)
                    recorder.step = step["id"]
                    started, t0 = _now(), time.perf_counter()
                    status, error, holder = "passed", None, {}
                    try:
                        _run_step(page, origin, step, timeout, holder)
                    except PWTimeout as e:
                        status, error = "timeout", f"Timeout {timeout}ms exceeded: {str(e).splitlines()[0][:200]}"
                    except PWError as e:
                        status, error = "failed", str(e).splitlines()[0][:300]
                    except Exception as e:  # unexpected engine/script error: record and continue
                        status, error = "failed", f"{type(e).__name__}: {str(e)[:300]}"
                    dur = (time.perf_counter() - t0) * 1000
                    metrics = holder.get("metrics")
                    if status == "passed":   # let in-flight requests (e.g. non-blocking fetches) settle, max 1 s
                        for _ in range(20):
                            if not any(x["state"] == "pending" and x["status"] is None and x["step"] == step["id"] for x in recorder.entries):
                                break
                            page.wait_for_timeout(50)
                    time.sleep(0.05)  # let trailing events flush
                    reqs, pending = recorder.collect(step["id"])
                    sink.add_step(rep, {"step_id": step["id"], "step_name": step["name"], "core": step.get("core", False),
                                        "status": status, "duration_ms": round(dur, 1), "error": error,
                                        "pending": pending or None, "started_at": started})
                    if reqs:
                        sink.add_requests(rep, step["id"], reqs)
                        all_requests.extend(reqs)
                    if metrics:
                        sink.add_page_metric(rep, step["id"], metrics)
                    errs = [e for e in recorder.js_errors if e["step"] == step["id"]]
                    if errs:
                        sink.add_js_errors(rep, step["id"], errs)
                    on_event(f"rep {rep} · {step['name']}: {status} ({dur:.0f} ms)", advance=True)
                blocked_total += len(recorder.blocked)
            finally:
                try:
                    context.close()
                except Exception:
                    pass
        _verify(enforcement, all_requests)
        return {"environment": {"browser": f"Chromium {browser_version} (headless={headless})", "engine": "Playwright (Python)",
                                "enforcement": enforcement, "blocked_requests": blocked_total,
                                "viewport": "412x915 (viewport emulation only)",
                                "notes": ["Browser HTTP cache is bypassed by request interception, so every load is a cold load.",
                                          "Metrics are from a desktop Chromium on this host; they are not physical-device measurements."]}}
    finally:
        # Always release browser resources, even after errors/cancellation.
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        with _open_lock:
            if browser:
                _open_browsers -= 1
        try:
            if pw:
                pw.stop()
        except Exception:
            pass
