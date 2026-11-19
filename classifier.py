"""Deterministic, documented issue classification. Severity is NEVER assigned by an LLM.

Rules (all thresholds come from the run's `rules` snapshot, editable in Settings):

R1 STEP_FAILED     per workflow step, over all attempts
     core step failed in 100% of attempts            -> critical
     other step failed in 100% of attempts           -> high
     failed in >= failure_ratio_high of attempts     -> high
     failed in fewer attempts (flaky)                -> medium
R2 REQUEST_FAILED  per METHOD+path: HTTP >= 400 or network failure
     failure share >= failure_ratio_high             -> high, otherwise medium
R3 SLOW_API        per METHOD+path: browser-measured latency > api_latency_ms in >= api_latency_min_exceed_ratio
                   of attempts -> severity_slow_api (default medium); median > multiplier x threshold -> high
R4 SLOW_PAGE_LOAD  per page path: median load-event time > page_load_ms -> severity_slow_page (default medium)
R5 JS_ERROR        per distinct uncaught exception / console error -> severity_js_error (default medium)
R6 LARGE_TRANSFER  per page path: median transferred bytes > page_transfer_kb -> severity_large_transfer (default low)
Regression findings (vs. a baseline) are produced by compare.py, not stored per run.
"""
import statistics
from collections import Counter, defaultdict

from .config import SEVERITY_VALUES


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def pctl(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = max(0, min(len(xs) - 1, int(round(p / 100 * len(xs) + 0.5)) - 1))
    return xs[k]


def _ep_key(r):
    return f"{r['method']} {r['path'].split('?')[0]}"


def _repro(run, step=None):
    p = run["profile"]
    cfg = (f"download {p.get('download_kbps') or 'unlimited'} kbps, upload {p.get('upload_kbps') or 'unlimited'} kbps, "
           f"latency +{p.get('latency_ms') or 0} ms, packet loss {p.get('packet_loss_pct') or 0}% (simulated), CPU slowdown {p.get('cpu_slowdown') or 1}x")
    steps = [
        f"In PocketTest AI open New Test and select target '{run['target_id']}' ({run['target_url']}).",
        f"Choose profile '{p['name']}' ({cfg}).",
        f"Choose workflow '{run['workflow_id']}' with {run['repetitions']} repetition(s) and start the test.",
    ]
    if run.get("target_meta") and "optimized" in run["target_meta"]:
        steps.append(f"Demo app mode at test time: optimized={run['target_meta']['optimized']}.")
    if step:
        steps.append(f"Observe workflow step: {step}.")
    return steps


def classify(run, data, rules, workflow):
    findings = []
    wf_steps = {s["id"]: s for s in workflow["steps"]}
    sev = lambda name: rules.get(name, "medium")

    # ---- R1 steps
    by_step = defaultdict(list)
    for s in data["steps"]:
        by_step[s["step_id"]].append(s)
    for sid, rows in by_step.items():
        failed = [r for r in rows if r["status"] != "passed"]
        if not failed:
            continue
        n, f = len(rows), len(failed)
        core = rows[0]["core"]
        ratio = f / n
        if ratio == 1:
            severity = "critical" if core else "high"
        elif ratio >= rules["failure_ratio_high"]:
            severity = "high"
        else:
            severity = "medium"
        timeouts = sum(1 for r in failed if r["status"] == "timeout")
        pending = sorted({p for r in failed for p in (r.get("pending") or [])})
        name = rows[0]["step_name"]
        if timeouts == f:
            title = f"Step \"{name}\" timed out in {f} of {n} attempts"
        elif core and ratio == 1:
            title = f"Core step \"{name}\" could not complete (failed {f} of {n} attempts)"
        else:
            title = f"Step \"{name}\" failed in {f} of {n} attempts"
        path = wf_steps.get(sid, {}).get("path", "")
        findings.append({"rule_id": "STEP_FAILED", "severity": severity, "title": title, "operation": f"{name} {path}".strip(),
                         "key": f"STEP_FAILED:{sid}",
                         "evidence": {"attempts": n, "failed_attempts": f, "timeouts": timeouts, "core_step": core,
                                      "errors": sorted({r["error"] for r in failed if r["error"]})[:3],
                                      "requests_pending_at_failure": pending,
                                      "step_timeout_ms": wf_steps.get(sid, {}).get("timeout_ms") or run["profile"].get("step_timeout_ms"),
                                      "median_step_duration_ms": median([r["duration_ms"] for r in failed]),
                                      "source": "browser (Playwright step execution)"},
                         "repro": _repro(run, name)})

    # ---- R2 failed requests / R3 slow API
    by_ep = defaultdict(list)
    for r in data["requests"]:
        by_ep[_ep_key(r)].append(r)
    for ep, rows in by_ep.items():
        failed = [r for r in rows if r["failed"]]
        if failed:
            ratio = len(failed) / len(rows)
            sim = sum(1 for r in failed if r["simulated_fault"])
            codes = Counter(str(r["status"]) if r["status"] else "no response" for r in failed)
            findings.append({
                "rule_id": "REQUEST_FAILED", "severity": "high" if ratio >= rules["failure_ratio_high"] else "medium",
                "title": f"{ep} failed in {len(failed)} of {len(rows)} requests" + (" (injected packet-loss simulation)" if sim == len(failed) else ""),
                "operation": ep, "key": f"REQUEST_FAILED:{ep}",
                "evidence": {"requests": len(rows), "failed": len(failed), "status_or_error_counts": dict(codes),
                             "simulated_faults": sim, "failure_texts": sorted({r["failure_text"] for r in failed if r["failure_text"]})[:3],
                             "source": "browser (Playwright network events)"},
                "repro": _repro(run, f"network request {ep}")})
        api_rows = [r for r in rows if r["is_api"] and r["duration_ms"] is not None and not r["failed"]]
        if api_rows:
            durs = [r["duration_ms"] for r in api_rows]
            over = [d for d in durs if d > rules["api_latency_ms"]]
            if len(over) / len(durs) >= rules["api_latency_min_exceed_ratio"]:
                med = median(durs)
                severity = "high" if med > rules["api_latency_high_multiplier"] * rules["api_latency_ms"] else sev("severity_slow_api")
                findings.append({
                    "rule_id": "SLOW_API", "severity": severity,
                    "title": f"{ep} exceeded {rules['api_latency_ms']:.0f} ms in {len(over)} of {len(durs)} requests",
                    "operation": ep, "key": f"SLOW_API:{ep}",
                    "evidence": {"threshold_ms": rules["api_latency_ms"], "latencies_ms": [round(d, 1) for d in durs],
                                 "exceeding": len(over), "total": len(durs), "median_ms": round(med, 1), "p95_ms": round(pctl(durs, 95), 1),
                                 "median_server_ms": median([r["server_ms"] for r in api_rows]),
                                 "median_transfer_bytes": median([r["transfer_bytes"] for r in api_rows]),
                                 "source": "browser latency (Playwright timing); server_ms from X-Server-Time-Ms header when present"},
                    "repro": _repro(run, f"request {ep}")})

    # ---- R4/R6 page metrics
    by_page = defaultdict(list)
    for m in data["page_metrics"]:
        by_page[m["path"]].append(m)
    for path, rows in by_page.items():
        loads = [m["load_ms"] for m in rows if m["load_ms"] is not None]
        step_id = rows[0]["step_id"]
        top = sorted([r for r in data["requests"] if r["step_id"] == step_id and r["transfer_bytes"]], key=lambda r: -r["transfer_bytes"])
        top_res = []
        seen = set()
        for r in top:
            if r["path"] not in seen:
                seen.add(r["path"]); top_res.append({"path": r["path"], "bytes": r["transfer_bytes"]})
            if len(top_res) == 3:
                break
        if loads and median(loads) > rules["page_load_ms"]:
            findings.append({"rule_id": "SLOW_PAGE_LOAD", "severity": sev("severity_slow_page"),
                             "title": f"Page {path} load time {median(loads):.0f} ms exceeds {rules['page_load_ms']:.0f} ms",
                             "operation": f"GET {path}", "key": f"SLOW_PAGE_LOAD:{path}",
                             "evidence": {"threshold_ms": rules["page_load_ms"], "load_ms_values": [round(x) for x in loads],
                                          "median_load_ms": round(median(loads)), "median_fcp_ms": median([m["fcp_ms"] for m in rows]),
                                          "median_lcp_ms": median([m["lcp_ms"] for m in rows]),
                                          "median_transfer_bytes": median([m["transfer_bytes"] for m in rows]),
                                          "largest_resources": top_res, "source": "browser (Navigation/Paint Timing API)"},
                             "repro": _repro(run, f"load {path}")})
        tr = median([m["transfer_bytes"] for m in rows])
        if tr is not None and tr > rules["page_transfer_kb"] * 1024:
            findings.append({"rule_id": "LARGE_TRANSFER", "severity": sev("severity_large_transfer"),
                             "title": f"Page {path} transfers {tr / 1024:.0f} KB (threshold {rules['page_transfer_kb']:.0f} KB)",
                             "operation": f"GET {path}", "key": f"LARGE_TRANSFER:{path}",
                             "evidence": {"threshold_kb": rules["page_transfer_kb"], "median_transfer_bytes": tr,
                                          "largest_resources": top_res, "source": "browser (Resource Timing API)"},
                             "repro": _repro(run, f"load {path}")})

    # ---- R5 JS errors
    by_err = defaultdict(list)
    for e in data["js_errors"]:
        by_err[e["message"]].append(e)
    for msg, rows in by_err.items():
        step = wf_steps.get(rows[0]["step_id"], {})
        findings.append({"rule_id": "JS_ERROR", "severity": sev("severity_js_error"),
                         "title": f"JavaScript error on {step.get('path', rows[0]['step_id'])}: {msg[:90]}",
                         "operation": f"{step.get('name', rows[0]['step_id'])} {step.get('path', '')}".strip(),
                         "key": f"JS_ERROR:{rows[0]['step_id']}:{msg[:60]}",
                         "evidence": {"message": msg, "kind": rows[0]["kind"], "occurrences": len(rows),
                                      "attempts": len({r["repetition"] for r in rows}),
                                      "source": "browser (pageerror/console events)"},
                         "repro": _repro(run, step.get("name"))})

    findings.sort(key=lambda f: -SEVERITY_VALUES[f["severity"]])
    return findings


def summarize(run, data, findings, rules):
    steps, reqs = data["steps"], data["requests"]
    passed = sum(1 for s in steps if s["status"] == "passed")
    pages = defaultdict(list)
    for m in data["page_metrics"]:
        pages[m["path"]].append(m)
    by_page = {p: {"load_ms": median([m["load_ms"] for m in rows]), "fcp_ms": median([m["fcp_ms"] for m in rows]),
                   "lcp_ms": median([m["lcp_ms"] for m in rows]), "dcl_ms": median([m["dom_content_loaded_ms"] for m in rows]),
                   "transfer_bytes": median([m["transfer_bytes"] for m in rows]), "samples": len(rows)} for p, rows in pages.items()}
    eps = defaultdict(list)
    for r in reqs:
        if r["is_api"]:
            eps[_ep_key(r)].append(r)
    by_endpoint = {}
    for ep, rows in eps.items():
        d = [r["duration_ms"] for r in rows if r["duration_ms"] is not None]
        by_endpoint[ep] = {"median_ms": median(d), "p95_ms": pctl(d, 95), "samples": len(d), "failed": sum(1 for r in rows if r["failed"]),
                           "median_server_ms": median([r["server_ms"] for r in rows]), "median_bytes": median([r["transfer_bytes"] for r in rows])}
    cats = Counter()
    cats["step_failed"] = len(steps) - passed
    cats["http_error"] = sum(1 for r in reqs if r["failed"] and not r["simulated_fault"] and (r["status"] or 0) >= 400)
    cats["network_failure"] = sum(1 for r in reqs if r["failed"] and not r["simulated_fault"] and not r["status"])
    cats["simulated_fault"] = sum(1 for r in reqs if r["simulated_fault"])
    cats["js_error"] = len(data["js_errors"])
    issue_counts = Counter(f["severity"] for f in findings)
    core_failed = sum(1 for s in steps if s["core"] and s["status"] != "passed")
    verdict = "failed" if (core_failed or any(f["severity"] in rules.get("fail_on_severity", []) for f in findings)) else "passed"
    all_api = [r["duration_ms"] for r in reqs if r["is_api"] and r["duration_ms"] is not None]
    return {"steps_total": len(steps), "steps_passed": passed, "steps_failed": len(steps) - passed, "core_steps_failed": core_failed,
            "median_load_ms": median([m["load_ms"] for m in data["page_metrics"]]),
            "slowest_page_load_ms": max([v["load_ms"] for v in by_page.values() if v["load_ms"] is not None], default=None),
            "median_api_ms": median(all_api), "p95_api_ms": pctl(all_api, 95), "api_requests": len(all_api),
            "failed_requests": sum(1 for r in reqs if r["failed"]), "js_errors": len(data["js_errors"]),
            "issue_counts": {k: issue_counts.get(k, 0) for k in ("critical", "high", "medium", "low")},
            "failure_categories": dict(cats), "by_page": by_page, "by_endpoint": by_endpoint,
            "latencies_ms": [round(x, 1) for x in all_api], "verdict": verdict}
