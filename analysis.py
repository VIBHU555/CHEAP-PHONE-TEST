"""Diagnostic report generation.

* The deterministic generator ALWAYS works (no API key needed) and only restates evidence recorded in the run,
  plus clearly-labelled hypotheses derived by simple, inspectable arithmetic.
* The optional LLM step (ANTHROPIC_API_KEY) adds *explanations and extra hypotheses* only. It never changes
  severity, evidence or verdict. Its output is labelled "AI-generated hypothesis - not confirmed".
"""
import json
import os
import urllib.request
from datetime import datetime, timezone

from . import config

LEGEND = {
    "measured": "Recorded by the browser/test engine during this run.",
    "simulated": "Produced by a deliberate simulation (e.g. request-level fault injection), not a real network fault.",
    "estimated": "Computed from measured values with simple arithmetic; not directly observed.",
    "hypothesis": "A possible explanation consistent with the evidence. NOT confirmed.",
}
NOT_MEASURED = ["Physical-device RAM, CPU, battery or thermal behaviour", "Application crashes on real devices",
                "Real mobile-carrier behaviour (packet loss, handovers, radio state)", "Server-side CPU/DB internals (only the demo app's X-Server-Time-Ms header)"]


def _kb(b):
    return f"{b / 1024:.0f} KB" if b is not None else "n/a"


def _ms(x):
    return f"{x:.0f} ms" if x is not None else "n/a"


def _bw_kbps(run):
    return run["profile"].get("download_kbps")


def _hyp(f, run):
    """Return (possible_causes, recommended_investigation, confidence_note)."""
    e, rid = f["evidence"], f["rule_id"]
    causes, recs = [], []
    if rid == "SLOW_API":
        med, srv, size = e["median_ms"], e.get("median_server_ms"), e.get("median_transfer_bytes")
        bw = _bw_kbps(run)
        if srv is not None and med:
            share = srv / med
            if share >= 0.7:
                causes.append({"text": f"About {share:.0%} of the median latency ({_ms(srv)} of {_ms(med)}) coincides with server-reported processing time, "
                                       "so work inside this endpoint or a dependency may be responsible.", "confidence": "medium", "basis": "estimated"})
            else:
                rest = med - srv
                txt = (f"Server-reported processing time is only {_ms(srv)} of the {_ms(med)} median; the remaining ~{_ms(rest)} happened outside server processing "
                       "(network latency, response transfer, or queueing).")
                if bw and size:
                    est = size * 8 / (bw * 1000) * 1000
                    txt += f" At the configured {bw} kbps, transferring {_kb(size)} alone would take roughly {_ms(est)} (estimated)."
                causes.append({"text": txt, "confidence": "medium", "basis": "estimated"})
                if size and size > 50_000:
                    causes.append({"text": f"The response is large ({_kb(size)}); payload size may be contributing to latency on slow links.",
                                   "confidence": "medium", "basis": "hypothesis"})
        else:
            causes.append({"text": "No server-side timing was available, so browser latency cannot be split into server and network parts.",
                           "confidence": "low", "basis": "hypothesis"})
        recs = ["Inspect server logs and tracing for this endpoint during the test window.", "Check response payload size and whether fields can be trimmed or paginated.",
                "Re-run with the Standard profile to separate server cost from network cost."]
        return causes, recs, "Latency figures are measured; the split between server and network is an estimate based on one header and configured bandwidth."
    if rid == "STEP_FAILED":
        pend = e.get("requests_pending_at_failure") or []
        if e["timeouts"]:
            t = f"The step did not finish within {e.get('step_timeout_ms')} ms in {e['timeouts']} attempt(s)."
            if pend:
                t += f" Requests still pending when the step ended: {', '.join(pend)}."
            causes.append({"text": t + " The endpoint or an upstream dependency may be slow or hanging.", "confidence": "medium", "basis": "hypothesis"})
        if e["errors"]:
            causes.append({"text": f"Recorded error(s): {'; '.join(e['errors'])}", "confidence": "high", "basis": "measured"})
        recs = ["Inspect server logs for the pending request(s) at the time of the test.", "Check whether the timeout limit is realistic for this operation.",
                "Re-run under the Standard profile to see whether the failure depends on network constraints."]
        return causes, recs, "That the step failed is confirmed. Why it failed is not established by this test alone."
    if rid == "REQUEST_FAILED":
        codes = e["status_or_error_counts"]
        if any(k.startswith("5") for k in codes):
            causes.append({"text": "5xx responses indicate the server reported an error; the handler or a dependency may be failing.", "confidence": "medium", "basis": "hypothesis"})
        if e["simulated_faults"]:
            causes.append({"text": f"{e['simulated_faults']} failure(s) were injected by the packet-loss simulation, not by the application or network.", "confidence": "high", "basis": "simulated"})
            causes.append({"text": "If the app does not retry or degrade gracefully, injected aborts may surface as user-visible errors.", "confidence": "low", "basis": "hypothesis"})
        recs = ["Inspect server error logs for the failing endpoint.", "Verify the client handles failures (retry, fallback, user message)."]
        return causes, recs, "Failure counts are measured. Root cause is not established."
    if rid in ("SLOW_PAGE_LOAD", "LARGE_TRANSFER"):
        big = e.get("largest_resources") or []
        total = e.get("median_transfer_bytes")
        bw = _bw_kbps(run)
        if big and total:
            share = sum(b["bytes"] for b in big) / total
            causes.append({"text": "Largest resources: " + ", ".join(f"{b['path']} ({_kb(b['bytes'])})" for b in big) +
                                   f" - together ~{share:.0%} of the page's transferred bytes.", "confidence": "high", "basis": "measured"})
        if bw and total:
            causes.append({"text": f"At {bw} kbps, moving {_kb(total)} takes at least ~{total * 8 / (bw * 1000):.1f} s (estimated), which may explain much of the load time.",
                           "confidence": "medium", "basis": "estimated"})
        causes.append({"text": "Render-blocking scripts or uncompressed/oversized assets may delay first paint on slow links.", "confidence": "low", "basis": "hypothesis"})
        recs = ["Compress and resize images, enable text compression, and split or defer large scripts.", "Compare load time with the Standard profile to confirm network dependence."]
        return causes, recs, "Timings and sizes are measured. Cause is a hypothesis."
    if rid == "JS_ERROR":
        causes.append({"text": f"The browser reported: {e['message']}", "confidence": "high", "basis": "measured"})
        causes.append({"text": "The script may reference an element or object that does not exist on this page.", "confidence": "low", "basis": "hypothesis"})
        recs = ["Open the page in browser DevTools and reproduce; use source maps to locate the failing line.", "Add an error boundary / null check and a regression test."]
        return causes, recs, "The exception is confirmed; its cause is a hypothesis."
    return causes, recs, ""


def _evidence_lines(f, run):
    e, out = f["evidence"], []
    for k, v in e.items():
        if k == "source" or v in (None, [], {}):
            continue
        kind = "simulated" if k == "simulated_faults" else "measured"
        out.append({"text": f"{k.replace('_', ' ')}: {json.dumps(v) if isinstance(v, (list, dict)) else v}", "kind": kind})
    out.append({"text": f"source: {e.get('source', 'test engine')}", "kind": "measured"})
    return out


def _observation(f):
    e = f["evidence"]
    rid = f["rule_id"]
    if rid == "SLOW_API":
        return f"The request exceeded the configured {e['threshold_ms']:.0f} ms threshold in {e['exceeding']} of {e['total']} attempts (median {e['median_ms']} ms)."
    if rid == "STEP_FAILED":
        return f"The step failed in {e['failed_attempts']} of {e['attempts']} attempts."
    if rid == "REQUEST_FAILED":
        return f"{e['failed']} of {e['requests']} requests to this endpoint failed."
    if rid == "SLOW_PAGE_LOAD":
        return f"Median load-event time was {e['median_load_ms']} ms against a {e['threshold_ms']:.0f} ms threshold."
    if rid == "LARGE_TRANSFER":
        return f"Median transferred bytes were {_kb(e['median_transfer_bytes'])} against a {e['threshold_kb']:.0f} KB threshold."
    if rid == "JS_ERROR":
        return f"An uncaught JavaScript error occurred {e['occurrences']} time(s) across {e['attempts']} attempt(s)."
    return f["title"]


def generate_report(run, data, findings, summary, llm=None):
    p = run["profile"]
    env = run.get("environment") or {}
    sev_counts = summary["issue_counts"]
    headline = (f"{summary['verdict'].upper()}: {summary['steps_failed']} of {summary['steps_total']} step executions failed; "
                f"{sum(sev_counts.values())} issue(s) found ({sev_counts['critical']} critical, {sev_counts['high']} high, "
                f"{sev_counts['medium']} medium, {sev_counts['low']} low) under profile '{p['name']}'.")
    items = []
    for i, f in enumerate(findings):
        causes, recs, note = _hyp(f, run)
        items.append({"finding_id": f.get("id", i), "rule_id": f["rule_id"], "severity": f["severity"], "title": f["title"],
                      "operation": f["operation"], "observation": _observation(f), "observation_status": "confirmed (measured)",
                      "evidence": _evidence_lines(f, run), "reproduction_steps": f["repro"], "possible_causes": causes,
                      "recommended_investigation": recs, "confidence_note": note})
    report = {"generator": "deterministic", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "headline": headline, "verdict": summary["verdict"], "legend": LEGEND,
              "measurement_notes": {"enforcement": env.get("enforcement", []), "not_measured": NOT_MEASURED,
                                    "environment": [env.get("browser"), env.get("viewport")] + env.get("notes", []),
                                    "blocked_requests": env.get("blocked_requests", 0)},
              "findings": items, "llm": {"status": "not_requested"}}
    if llm is not None:
        report = llm_enhance(report, llm)
    return report


# ---------------------------------------------------------------- optional LLM
def llm_configured():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def anthropic_call(prompt, timeout=40):
    """Minimal stdlib client for the Anthropic Messages API. Key is read from the environment only."""
    key = os.environ["ANTHROPIC_API_KEY"]
    body = json.dumps({"model": config.ANTHROPIC_MODEL, "max_tokens": 1500, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST",
                                 headers={"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # nosec - fixed https endpoint
        payload = json.loads(r.read())
    return "".join(b.get("text", "") for b in payload.get("content", []))


def llm_enhance(report, call):
    """`call(prompt) -> str`. On any failure the deterministic report is returned unchanged with llm.status='error'."""
    compact = [{"id": f["finding_id"], "rule": f["rule_id"], "severity": f["severity"], "title": f["title"],
                "observation": f["observation"], "evidence": [e["text"] for e in f["evidence"]][:12]} for f in report["findings"]]
    prompt = ("You assist a software tester. Below are findings from an automated browser test, as JSON. "
              "Severity and evidence are fixed; do not change them. For each finding give a short explanation and up to 2 additional "
              "possible causes, each phrased as a hypothesis (use 'may' or 'could'); never claim a root cause is established. "
              "Reply with ONLY JSON: {\"summary\": str, \"findings\": [{\"id\": <id>, \"explanation\": str, \"additional_hypotheses\": [str]}]}\n\n"
              + json.dumps({"run_headline": report["headline"], "findings": compact}))
    try:
        text = call(prompt).strip()
        if text.startswith("```"):
            text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
        parsed = json.loads(text)
        by_id = {str(x.get("id")): x for x in parsed.get("findings", []) if isinstance(x, dict)}
        for f in report["findings"]:
            x = by_id.get(str(f["finding_id"]))
            if x:
                f["ai_explanation"] = {"label": "AI-generated hypothesis - not confirmed", "text": str(x.get("explanation", ""))[:1200],
                                       "additional_hypotheses": [str(h)[:400] for h in (x.get("additional_hypotheses") or [])][:2]}
        if parsed.get("summary"):
            report["ai_summary"] = {"label": "AI-generated summary - not confirmed", "text": str(parsed["summary"])[:1500]}
        report["generator"] = "deterministic+llm"
        report["llm"] = {"status": "used", "model": config.ANTHROPIC_MODEL}
    except Exception as e:  # network, auth, parse errors: keep deterministic report
        report["llm"] = {"status": "error", "detail": f"{type(e).__name__}: {str(e)[:200]}", "fallback": "deterministic report shown"}
    return report
