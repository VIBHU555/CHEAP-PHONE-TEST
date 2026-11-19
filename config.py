"""Configuration, default severity rules and built-in testing profiles."""
import copy
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # backend/
PROJECT_ROOT = ROOT.parent
DB_PATH = os.environ.get("POCKETTEST_DB", str(ROOT / "data" / "pockettest.sqlite3"))
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DEMO_URL = os.environ.get("POCKETTEST_DEMO_URL", "http://127.0.0.1:5055")
MAX_CONCURRENT_RUNS = int(os.environ.get("POCKETTEST_MAX_CONCURRENT", "1"))
MAX_REPETITIONS = 10
DEFAULT_STEP_TIMEOUT_MS = 15000
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

# Severity / classification rules. All values are user-editable (Settings page).
DEFAULT_RULES = {
    "api_latency_ms": 800,                # API call slower than this counts as "exceeding"
    "api_latency_min_exceed_ratio": 0.5,  # share of attempts that must exceed it to raise an issue
    "api_latency_high_multiplier": 4.0,   # median > multiplier * threshold escalates medium -> high
    "page_load_ms": 3000,                 # load-event time threshold for a page
    "page_transfer_kb": 500,              # transferred bytes per page threshold (low severity)
    "failure_ratio_high": 0.5,            # failure share at/above which a failure is "high"
    "regression_pct": 25.0,               # comparison: % worsening treated as regression ...
    "regression_min_abs_ms": 100.0,       # ... only if also worse by at least this many ms
    "severity_slow_api": "medium",
    "severity_slow_page": "medium",
    "severity_js_error": "medium",
    "severity_large_transfer": "low",
    "fail_on_severity": ["critical", "high"],  # run verdict = failed if any finding has these severities
}
SEVERITIES = ["critical", "high", "medium", "low"]
SEVERITY_VALUES = {"critical": 4, "high": 3, "medium": 2, "low": 1}

# Built-in profiles. These are EXAMPLE test configurations, not measurements of any
# particular phone or carrier network.
BUILTIN_PROFILES = [
    {"id": "standard", "name": "Standard Network", "builtin": True,
     "description": "No network or CPU shaping. Baseline for comparison.",
     "download_kbps": None, "upload_kbps": None, "latency_ms": 0, "packet_loss_pct": 0, "cpu_slowdown": 1,
     "step_timeout_ms": 15000},
    {"id": "constrained", "name": "Constrained Network", "builtin": True,
     "description": "Example: 1000 kbps down / 400 kbps up, 150 ms added latency, 4x CPU slowdown.",
     "download_kbps": 1000, "upload_kbps": 400, "latency_ms": 150, "packet_loss_pct": 0, "cpu_slowdown": 4,
     "step_timeout_ms": 15000},
    {"id": "high_latency", "name": "High-Latency Network", "builtin": True,
     "description": "Example: 5000 kbps down / 1000 kbps up, 600 ms added latency.",
     "download_kbps": 5000, "upload_kbps": 1000, "latency_ms": 600, "packet_loss_pct": 0, "cpu_slowdown": 1,
     "step_timeout_ms": 15000},
    {"id": "intermittent", "name": "Intermittent Network", "builtin": True,
     "description": "Example: 1500 kbps, 200 ms latency, 10% of requests aborted (simulated fault injection).",
     "download_kbps": 1500, "upload_kbps": 600, "latency_ms": 200, "packet_loss_pct": 10, "cpu_slowdown": 1,
     "step_timeout_ms": 15000},
]


def default_rules():
    return copy.deepcopy(DEFAULT_RULES)


def builtin_targets():
    """Registered, explicitly authorised test targets. Extra targets may be added via
    POCKETTEST_ALLOWED_TARGETS (comma-separated http(s) origins on localhost/loopback or an
    explicitly authorised host)."""
    targets = [{
        "id": "demo-shop", "name": "PocketShop (local demo app)", "url": DEMO_URL, "kind": "demo",
        "description": "Controlled demo app with deliberate, reproducible problems.",
        "workflows": ["shop_checkout", "api_health", "smoke_load"],
    }]
    for i, origin in enumerate(filter(None, (s.strip() for s in os.environ.get("POCKETTEST_ALLOWED_TARGETS", "").split(",")))):
        targets.append({"id": f"custom-{i + 1}", "name": f"Authorised target {origin}", "url": origin, "kind": "custom",
                        "description": "Configured via POCKETTEST_ALLOWED_TARGETS.", "workflows": ["smoke_load"]})
    return targets
