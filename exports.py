"""JSON / CSV export of a run."""
import csv
import io

CSV_PARTS = {
    "findings": ["rule_id", "severity", "title", "operation", "key"],
    "requests": ["repetition", "step_id", "method", "path", "resource_type", "status", "failed", "failure_text", "simulated_fault",
                 "duration_ms", "transfer_bytes", "server_ms", "is_api", "source"],
    "steps": ["repetition", "step_id", "step_name", "core", "status", "duration_ms", "error", "started_at"],
    "page_metrics": ["repetition", "step_id", "path", "nav_duration_ms", "dom_content_loaded_ms", "load_ms", "fcp_ms", "lcp_ms", "resource_count", "transfer_bytes", "source"],
    "js_errors": ["repetition", "step_id", "kind", "message"],
}


def run_bundle(run, data, report):
    return {"export_format": "pockettest-ai/run@1", "run": run, **data, "report": report}


def _safe(v):
    # Neutralise spreadsheet formula injection from untrusted page text.
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v
    return v


def to_csv(data, part="findings"):
    if part not in CSV_PARTS:
        raise ValueError(f"Unknown CSV part '{part}'. Choose one of {sorted(CSV_PARTS)}")
    cols = CSV_PARTS[part]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for row in data[part]:
        w.writerow([_safe(row.get(c)) for c in cols])
    return buf.getvalue()
