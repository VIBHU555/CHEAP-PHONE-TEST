"""Run orchestration: input validation, concurrency limiting, execution thread, persistence."""
import json
import re
import threading
import urllib.request

from . import analysis, config, engine
from .classifier import classify, summarize
from .db import now_iso
from .security import TargetRejected, validate_target_url
from .workflows import get_workflow


class ValidationError(ValueError):
    pass


class Busy(RuntimeError):
    pass


def _num(v, name, lo, hi, allow_none=False):
    if v is None and allow_none:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValidationError(f"{name} must be a number.")
    if not (lo <= v <= hi):
        raise ValidationError(f"{name} must be between {lo} and {hi}.")
    return v


def validate_profile(p):
    if not isinstance(p, dict):
        raise ValidationError("Profile must be an object.")
    name = p.get("name")
    if not isinstance(name, str) or not (1 <= len(name.strip()) <= 60):
        raise ValidationError("name must be 1-60 characters.")
    return {"name": name.strip(), "description": str(p.get("description", ""))[:200],
            "download_kbps": _num(p.get("download_kbps"), "download_kbps", 50, 1_000_000, True),
            "upload_kbps": _num(p.get("upload_kbps"), "upload_kbps", 50, 1_000_000, True),
            "latency_ms": _num(p.get("latency_ms", 0), "latency_ms", 0, 10_000),
            "packet_loss_pct": _num(p.get("packet_loss_pct", 0), "packet_loss_pct", 0, 100),
            "cpu_slowdown": _num(p.get("cpu_slowdown", 1), "cpu_slowdown", 1, 20),
            "step_timeout_ms": int(_num(p.get("step_timeout_ms", 15000), "step_timeout_ms", 1000, 120_000))}


def validate_rules(r, base):
    if not isinstance(r, dict):
        raise ValidationError("Rules must be an object.")
    out = dict(base)
    nums = {"api_latency_ms": (1, 600_000), "api_latency_min_exceed_ratio": (0.01, 1), "api_latency_high_multiplier": (1, 1000),
            "page_load_ms": (1, 600_000), "page_transfer_kb": (1, 10_000_000), "failure_ratio_high": (0.01, 1),
            "regression_pct": (1, 10_000), "regression_min_abs_ms": (0, 600_000)}
    for k, (lo, hi) in nums.items():
        if k in r:
            out[k] = float(_num(r[k], k, lo, hi))
    for k in ("severity_slow_api", "severity_slow_page", "severity_js_error", "severity_large_transfer"):
        if k in r:
            if r[k] not in config.SEVERITIES:
                raise ValidationError(f"{k} must be one of {config.SEVERITIES}")
            out[k] = r[k]
    if "fail_on_severity" in r:
        v = r["fail_on_severity"]
        if not isinstance(v, list) or any(x not in config.SEVERITIES for x in v):
            raise ValidationError("fail_on_severity must be a list of severities.")
        out["fail_on_severity"] = v
    return out


class RunManager:
    def __init__(self, repo, max_concurrent=None, headless=True, check_reachable=True, llm_call=None):
        self.repo = repo
        self.sem = threading.BoundedSemaphore(max_concurrent or config.MAX_CONCURRENT_RUNS)
        self.cancel_flags = {}
        self.threads = {}
        self.headless = headless
        self.check_reachable = check_reachable
        self.llm_call = llm_call            # injectable for tests
        repo.mark_interrupted()

    # ---- catalogues
    def targets(self):
        return config.builtin_targets()

    def profiles(self):
        return config.BUILTIN_PROFILES + self.repo.get_setting("custom_profiles", [])

    def rules(self):
        return {**config.default_rules(), **self.repo.get_setting("rules", {})}

    def target_meta(self, target):
        if target["kind"] != "demo":
            return {}
        try:
            with urllib.request.urlopen(target["url"].rstrip("/") + "/_admin/mode", timeout=2) as r:
                return json.loads(r.read())
        except Exception:
            return {"unavailable": True}

    # ---- start
    def start(self, params):
        if not isinstance(params, dict):
            raise ValidationError("Request body must be a JSON object.")
        targets = {t["id"]: t for t in self.targets()}
        target = targets.get(params.get("target_id"))
        if not target:
            raise ValidationError("Unknown target_id.")
        if params.get("target_url") is not None:      # optional; must resolve to the SAME registered origin
            try:
                validate_target_url(params["target_url"], [target["url"]])
            except TargetRejected as e:
                raise ValidationError(f"Target rejected: {e}")
        try:
            validate_target_url(target["url"], [t["url"] for t in targets.values()])
        except TargetRejected as e:
            raise ValidationError(f"Target rejected: {e}")
        profile = next((p for p in self.profiles() if p["id"] == params.get("profile_id")), None)
        if not profile:
            raise ValidationError("Unknown profile_id.")
        wid = params.get("workflow_id")
        workflow = get_workflow(wid) if isinstance(wid, str) else None
        if not workflow or wid not in target["workflows"]:
            raise ValidationError("Unknown workflow_id, or workflow not supported by this target.")
        reps = params.get("repetitions", 3)
        if isinstance(reps, bool) or not isinstance(reps, int) or not (1 <= reps <= config.MAX_REPETITIONS):
            raise ValidationError(f"repetitions must be an integer 1-{config.MAX_REPETITIONS}.")
        label = params.get("label") or ""
        if not isinstance(label, str) or len(label) > 80:
            raise ValidationError("label must be a string up to 80 characters.")
        if self.check_reachable:
            try:
                urllib.request.urlopen(target["url"], timeout=3).read(1)
            except Exception as e:
                raise ValidationError(f"Target is not reachable at {target['url']}: {type(e).__name__}. Start it first (see README).")
        if not self.sem.acquire(blocking=False):
            raise Busy("Another test is already running (concurrency limit reached).")
        try:
            meta = self.target_meta(target)
            rid = self.repo.create_run(label=label.strip(), target=target, profile=profile, workflow_id=wid, repetitions=reps,
                                       rules=self.rules(), target_meta=meta)
            self.cancel_flags[rid] = threading.Event()
            t = threading.Thread(target=self._execute, args=(rid, target, workflow), daemon=True, name=f"run-{rid}")
            self.threads[rid] = t
            t.start()
            return rid
        except Exception:
            self.sem.release()
            raise

    def cancel(self, rid):
        ev = self.cancel_flags.get(rid)
        if ev:
            ev.set()
            return True
        return False

    def wait(self, rid, timeout=600):
        t = self.threads.get(rid)
        if t:
            t.join(timeout)

    # ---- execution
    def _execute(self, rid, target, workflow):
        repo = self.repo
        run = repo.get_run(rid)
        events, counter = [], {"done": 0}
        total = run["repetitions"] * len(workflow["steps"])

        def on_event(msg, advance=False):
            events.append({"t": now_iso(), "msg": msg})
            if advance:
                counter["done"] += 1
            repo.update_run(rid, progress={"events": events[-200:], "done": counter["done"], "total": total})

        class Sink:
            add_step = lambda _, rep, s: repo.add_step(rid, rep, s)
            add_requests = lambda _, rep, sid, r: repo.add_requests(rid, rep, sid, r)
            add_page_metric = lambda _, rep, sid, m: repo.add_page_metric(rid, rep, sid, m)
            add_js_errors = lambda _, rep, sid, e: repo.add_js_errors(rid, rep, sid, e)

        try:
            repo.update_run(rid, status="running", started_at=now_iso(), progress={"events": [], "done": 0, "total": total})
            on_event(f"Starting '{workflow['name']}' against {target['url']} with profile '{run['profile']['name']}'")
            out = engine.run_workflow(origin=target["url"], profile=run["profile"], workflow=workflow, repetitions=run["repetitions"],
                                      seed=7, sink=Sink(), on_event=on_event,
                                      should_cancel=self.cancel_flags[rid].is_set, headless=self.headless)
            repo.update_run(rid, environment=out["environment"])
            self.finalize(rid, workflow)
            on_event("Run completed; findings and report generated")
        except engine.RunCancelled:
            repo.update_run(rid, status="cancelled", finished_at=now_iso(), error="Cancelled by user")
        except engine.EnforcementError as e:
            repo.update_run(rid, status="failed", finished_at=now_iso(), error=f"Requested constraints could not be enforced; run aborted. {e}")
        except Exception as e:
            repo.update_run(rid, status="failed", finished_at=now_iso(), error=f"{type(e).__name__}: {str(e)[:400]}")
        finally:
            self.cancel_flags.pop(rid, None)
            self.sem.release()

    def finalize(self, rid, workflow=None):
        """Classify, summarise and generate the report for a finished run (also used for re-analysis)."""
        run = self.repo.get_run(rid)
        workflow = workflow or get_workflow(run["workflow_id"])
        data = self.repo.run_data(rid)
        findings = classify(run, data, run["rules"], workflow)
        self.repo.replace_findings(rid, findings)
        summary = summarize(run, data, findings, run["rules"])
        self.repo.update_run(rid, status="completed", finished_at=now_iso(), summary=summary, verdict=summary["verdict"])
        run = self.repo.get_run(rid)
        data = self.repo.run_data(rid)
        report = analysis.generate_report(run, data, data["findings"], summary)
        self.repo.save_report(rid, report["generator"], report)

    def regenerate_report(self, rid, use_llm=False):
        run = self.repo.get_run(rid)
        if not run or run["status"] != "completed":
            raise ValidationError("Run not found or not completed.")
        data = self.repo.run_data(rid)
        llm = None
        if use_llm:
            llm = self.llm_call or (analysis.anthropic_call if analysis.llm_configured() else None)
            if llm is None:
                raise ValidationError("LLM is not configured (set ANTHROPIC_API_KEY on the server). The deterministic report remains available.")
        report = analysis.generate_report(run, data, data["findings"], run["summary"], llm=llm)
        self.repo.save_report(rid, report["generator"], report)
        return report
