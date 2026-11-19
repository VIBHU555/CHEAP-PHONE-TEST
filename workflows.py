"""Predefined test workflows. A workflow is an ordered list of declarative steps executed by engine.py.

Step types: navigate | form | click_wait | api
`core: True` means the user journey cannot be considered working if the step fails.
"""

WORKFLOWS = {
    "smoke_load": {
        "id": "smoke_load", "name": "Smoke: load home page",
        "description": "Loads the target's home page and records page timing, failed requests and JavaScript errors. Works on any registered target.",
        "steps": [
            {"id": "load_home", "name": "Load home page", "type": "navigate", "path": "/", "core": True},
        ],
    },
    "api_health": {
        "id": "api_health", "name": "API request execution",
        "description": "Calls the demo shop's API endpoints directly from the browser and records latency and failures.",
        "steps": [
            {"id": "open_origin", "name": "Open API health endpoint", "type": "navigate", "path": "/api/health", "core": True, "measure_page": False},
            {"id": "api_products", "name": "GET /api/products", "type": "api", "method": "GET", "path": "/api/products", "core": True, "require_ok": True},
            {"id": "api_recs", "name": "GET /api/recommendations", "type": "api", "method": "GET", "path": "/api/recommendations", "core": False, "require_ok": False},
            {"id": "api_order", "name": "POST /api/order", "type": "api", "method": "POST", "path": "/api/order",
             "body": {"name": "Test User", "email": "test@example.com"}, "core": True, "require_ok": True},
        ],
    },
    "shop_checkout": {
        "id": "shop_checkout", "name": "Shop checkout journey",
        "description": "Home -> product list (API) -> checkout form submit (API POST) -> report generation (slow API) -> About page.",
        "steps": [
            {"id": "home", "name": "Load home page", "type": "navigate", "path": "/", "wait_selector": "#hero", "core": True},
            {"id": "products", "name": "Open product list", "type": "navigate", "path": "/products", "wait_selector": ".product-card", "core": True},
            {"id": "checkout", "name": "Fill and submit checkout form", "type": "form", "path": "/checkout",
             "fill": {"#name": "Test User", "#email": "test@example.com"}, "click": "#place", "wait_selector": "#order-ok", "core": True},
            {"id": "report", "name": "Generate sales report", "type": "click_wait", "path": "/reports", "click": "#gen-report",
             "wait_selector": "#report-ready", "timeout_ms": 6000, "core": False},
            {"id": "about", "name": "Open About page", "type": "navigate", "path": "/about", "wait_selector": "#about-text", "core": False},
        ],
    },
}


def get_workflow(wid):
    return WORKFLOWS.get(wid)


def list_workflows():
    return list(WORKFLOWS.values())
