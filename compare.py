"""Baseline-vs-new run comparison with compatibility checks."""
from .classifier import median

PROFILE_KEYS = ["download_kbps", "upload_kbps", "latency_ms", "packet_loss_pct", "cpu_slowdown"]


class Incompatible(ValueError):
    pass


def pct(a, b):
    """Percentage change from a to b; None when mathematically undefined (missing or zero baseline)."""
    if a is None or b is None or a == 0:
        return None
    return round((b - a) / abs(a) * 100, 1)


def _delta(a, b):
    return {"baseline": a, "new": b, "abs": None if a is None or b is None else round(b - a, 1), "pct": pct(a, b)}


def compatibility(ra, rb):
    for r, n in ((ra, "baseline"), (rb, "new")):
        if r["status"] != "completed":
            raise Incompatible(f"The {n} run has status '{r['status']}' and cannot be compared.")
    if ra["workflow_id"] != rb["workflow_id"]:
        raise Incompatible(f"Different workflows ({ra['workflow_id']} vs {rb['workflow_id']}): results are not comparable.")
    if ra["target_id"] != rb["target_id"]:
        raise Incompatible("Different targets: results are not comparable.")
    warnings, notes = [], []
    diffs = [k for k in PROFILE_KEYS if ra["profile"].get(k) != rb["profile"].get(k)]
    if diffs:
        warnings.append("Test conditions differ (" + ", ".join(f"{k}: {ra['profile'].get(k)} vs {rb['profile'].get(k)}" for k in diffs) +
                        "). Differences reflect the changed conditions as well as any application change.")
    if ra["repetitions"] != rb["repetitions"]:
        warnings.append(f"Different repetition counts ({ra['repetitions']} vs {rb['repetitions']}); medians rest on different sample sizes.")
    rule_keys = ("api_latency_ms", "page_load_ms", "page_transfer_kb")
    if any(ra["rules"].get(k) != rb["rules"].get(k) for k in rule_keys):
        warnings.append("Classification thresholds differ between runs; finding counts may not be directly comparable.")
    ma, mb = (ra.get("target_meta") or {}), (rb.get("target_meta") or {})
    if ma.get("optimized") != mb.get("optimized"):
        notes.append(f"Demo app mode changed: optimized={ma.get('optimized')} -> optimized={mb.get('optimized')}.")
    return warnings, notes


def compare_runs(ra, rb, fa, fb):
    """ra/rb: run rows incl. summary; fa/fb: findings lists."""
    warnings, notes = compatibility(ra, rb)
    sa, sb = ra["summary"], rb["summary"]
    rules = rb["rules"]
    pages = {}
    for path in sorted(set(sa["by_page"]) | set(sb["by_page"])):
        a, b = sa["by_page"].get(path, {}), sb["by_page"].get(path, {})
        pages[path] = {m: _delta(a.get(m), b.get(m)) for m in ("load_ms", "fcp_ms", "lcp_ms", "transfer_bytes")}
    eps = {}
    for ep in sorted(set(sa["by_endpoint"]) | set(sb["by_endpoint"])):
        a, b = sa["by_endpoint"].get(ep, {}), sb["by_endpoint"].get(ep, {})
        eps[ep] = {"median_ms": _delta(a.get("median_ms"), b.get("median_ms")), "p95_ms": _delta(a.get("p95_ms"), b.get("p95_ms")),
                   "failed": _delta(a.get("failed"), b.get("failed")), "median_bytes": _delta(a.get("median_bytes"), b.get("median_bytes"))}
    totals = {k: _delta(sa.get(k), sb.get(k)) for k in ("steps_failed", "failed_requests", "js_errors", "slowest_page_load_ms", "median_load_ms", "median_api_ms", "p95_api_ms")}
    for sev in ("critical", "high", "medium", "low"):
        totals[f"issues_{sev}"] = _delta(sa["issue_counts"].get(sev, 0), sb["issue_counts"].get(sev, 0))
    ka, kb = {f["key"]: f for f in fa}, {f["key"]: f for f in fb}
    new_f = [{"key": k, "severity": f["severity"], "title": f["title"]} for k, f in kb.items() if k not in ka]
    resolved = [{"key": k, "severity": f["severity"], "title": f["title"]} for k, f in ka.items() if k not in kb]
    persisting = [{"key": k, "title": kb[k]["title"], "severity_before": ka[k]["severity"], "severity_now": kb[k]["severity"]} for k in ka if k in kb]
    regressions = []

    def check(label, d):
        if d["pct"] is not None and d["pct"] >= rules["regression_pct"] and (d["abs"] or 0) >= rules["regression_min_abs_ms"]:
            regressions.append({"metric": label, "baseline": d["baseline"], "new": d["new"], "pct": d["pct"], "severity": "medium",
                                "rule": f">= {rules['regression_pct']}% and >= {rules['regression_min_abs_ms']} ms worse"})
    for path, m in pages.items():
        check(f"{path} load_ms", m["load_ms"])
    for ep, m in eps.items():
        check(f"{ep} median_ms", m["median_ms"])
    return {"baseline": {"id": ra["id"], "label": ra["label"], "profile": ra["profile"]["name"], "created_at": ra["created_at"], "verdict": ra["verdict"], "target_meta": ra["target_meta"]},
            "new": {"id": rb["id"], "label": rb["label"], "profile": rb["profile"]["name"], "created_at": rb["created_at"], "verdict": rb["verdict"], "target_meta": rb["target_meta"]},
            "warnings": warnings, "notes": notes, "pages": pages, "endpoints": eps, "totals": totals,
            "new_failures": new_f, "resolved_failures": resolved, "persisting": persisting, "regressions": regressions,
            "pct_note": "Percent change is shown only when the baseline value is present and non-zero."}
