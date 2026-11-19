"""PocketTest AI - controlled demonstration application ("PocketShop").

This app contains DELIBERATE, REPRODUCIBLE problems used to demonstrate the
testing platform. It is isolated from production code and must never be
deployed. A mode switch (/_admin/mode) toggles between:

  optimized = False  -> the "before" version (slow, heavy, buggy on purpose)
  optimized = True   -> the "after" version (a sample optimisation)

Deliberate problems when optimized = False:
  * /api/products        : 450 ms server delay + ~120 KB verbose JSON payload
  * /api/recommendations : always HTTP 500 (page degrades gracefully)
  * /api/report          : 9 s server delay (the workflow step has a 6 s limit)
  * /                    : ~380 KB blocking JS bundle + hero image + 60 KB CSS
  * /about               : inline script throws a TypeError (JavaScript exception)
"""
import base64
import io
import os
import random
import threading
import time

from flask import Flask, Response, g, jsonify, request

app = Flask(__name__)
STATE = {"optimized": False}
_lock = threading.Lock()
_cache = {}


def _noise_bytes(n, seed):
    rnd = random.Random(seed)
    return bytes(rnd.getrandbits(8) for _ in range(n))


def _bundle(size_kb, seed):
    key = ("bundle", size_kb)
    if key not in _cache:
        pad = base64.b64encode(_noise_bytes(int(size_kb * 1024 * 0.75), seed)).decode()
        _cache[key] = ("/*" + pad + "*/\nwindow.__pocketshopBundle = true;\n").encode()
    return _cache[key]


def _css(size_kb):
    key = ("css", size_kb)
    if key not in _cache:
        pad = base64.b64encode(_noise_bytes(int(size_kb * 1024 * 0.75), 7)).decode()
        base = ("body{font-family:system-ui,sans-serif;margin:0;background:#fafafa;color:#222}"
                "nav{background:#1f2a44;padding:12px}nav a{color:#fff;margin-right:16px}"
                "main{padding:20px}.card{border:1px solid #ddd;padding:12px;margin:8px;display:inline-block;width:200px}"
                "#hero{width:100%;max-width:800px;height:auto;display:block}"
                "button{padding:8px 14px}input{padding:6px;margin:4px 0;display:block}")
        _cache[key] = (base + "\n/*" + pad + "*/").encode()
    return _cache[key]


def _hero(w, h, quality):
    key = ("hero", w, h, quality)
    if key not in _cache:
        import numpy as np
        from PIL import Image
        rng = np.random.default_rng(42)
        arr = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, "JPEG", quality=quality)
        _cache[key] = buf.getvalue()
    return _cache[key]


def opt():
    return STATE["optimized"]


@app.before_request
def _t0():
    g.t0 = time.perf_counter()


@app.after_request
def _headers(resp):
    ms = (time.perf_counter() - g.t0) * 1000
    resp.headers["X-Server-Time-Ms"] = f"{ms:.1f}"   # server-side timing, separate from browser timing
    resp.headers["Cache-Control"] = "no-store"
    return resp


NAV = ('<nav><a href="/">Home</a><a href="/products">Products</a><a href="/checkout">Checkout</a>'
       '<a href="/reports">Reports</a><a href="/about">About</a></nav>')


def page(title, body, head=""):
    return Response(f"<!doctype html><html lang=en><head><meta charset=utf-8><title>{title}</title>"
                    f"<meta name=viewport content='width=device-width,initial-scale=1'>{head}</head>"
                    f"<body>{NAV}<main>{body}</main></body></html>", mimetype="text/html")


@app.get("/")
def home():
    if opt():
        head = '<link rel=stylesheet href="/static/site.css?v=min"><script defer src="/static/app.bundle.js?v=min"></script>'
        img = '<img id=hero src="/static/hero.jpg?v=min" width=400 height=250 alt="PocketShop hero">'
    else:
        head = '<link rel=stylesheet href="/static/site.css"><script src="/static/app.bundle.js"></script>'
        img = '<img id=hero src="/static/hero.jpg" width=900 height=560 alt="PocketShop hero">'
    return page("PocketShop - Home", f"<h1>PocketShop</h1>{img}<p id=tagline>Everyday items, delivered.</p>", head)


@app.get("/products")
def products():
    return page("PocketShop - Products", """<h1>Products</h1><div id=list>Loading...</div><div id=recs></div>
<script>
fetch('/api/products').then(r=>r.json()).then(d=>{
  document.getElementById('list').innerHTML=d.items.slice(0,12).map(p=>'<div class="card product-card"><b>'+p.name+'</b><br>Rs '+p.price+'</div>').join('');
});
fetch('/api/recommendations').then(r=>{ if(!r.ok) throw new Error('recs unavailable'); return r.json(); })
 .then(d=>{document.getElementById('recs').textContent='Recommended: '+d.items.join(', ');}).catch(()=>{});
</script>""")


@app.get("/checkout")
def checkout():
    return page("PocketShop - Checkout", """<h1>Checkout</h1>
<label>Name<input id=name aria-label=Name></label><label>Email<input id=email aria-label=Email></label>
<button id=place>Place order</button><p id=status></p>
<script>
document.getElementById('place').onclick=async()=>{
  const r=await fetch('/api/order',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:document.getElementById('name').value,email:document.getElementById('email').value})});
  const d=await r.json();
  const s=document.getElementById('status'); s.id='order-ok'; s.textContent='Order '+d.order_id+' confirmed';
};
</script>""")


@app.get("/reports")
def reports():
    return page("PocketShop - Reports", """<h1>Sales report</h1><button id=gen-report>Generate report</button><p id=rstate></p>
<script>
document.getElementById('gen-report').onclick=async()=>{
  const r=await fetch('/api/report'); const d=await r.json();
  const p=document.getElementById('rstate'); p.id='report-ready'; p.textContent='Report ready: '+d.rows+' rows';
};
</script>""")


@app.get("/about")
def about():
    script = "" if opt() else "<script>document.getElementById('team-widget').render();</script>"
    return page("PocketShop - About", f"<h1>About</h1><p id=about-text>PocketShop is a demo application.</p>{script}")


@app.get("/static/app.bundle.js")
def bundle():
    return Response(_bundle(30 if opt() else 380, 1), mimetype="application/javascript")


@app.get("/static/site.css")
def css():
    return Response(_css(4 if opt() else 60), mimetype="text/css")


@app.get("/static/hero.jpg")
def hero():
    data = _hero(400, 250, 60) if opt() else _hero(900, 560, 75)
    return Response(data, mimetype="image/jpeg")


@app.get("/api/products")
def api_products():
    time.sleep(0.04 if opt() else 0.45)
    n = 12 if opt() else 400
    items = []
    for i in range(n):
        it = {"id": i, "name": f"Item {i}", "price": 100 + i}
        if not opt():
            it.update({"description": "Verbose legacy description " * 8, "meta": {"tags": ["a"] * 6}})
        items.append(it)
    return jsonify({"items": items})


@app.get("/api/recommendations")
def api_recs():
    if opt():
        return jsonify({"items": ["Item 3", "Item 7"]})
    return jsonify({"error": "recommendation service failure (deliberate demo fault)"}), 500


@app.post("/api/order")
def api_order():
    time.sleep(0.03 if opt() else 0.12)
    return jsonify({"order_id": "PS-1001"})


@app.get("/api/report")
def api_report():
    time.sleep(0.15 if opt() else 9.0)
    return jsonify({"rows": 1200})


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "optimized": opt()})


@app.get("/_admin/mode")
def get_mode():
    return jsonify({"optimized": opt(), "app_version": "demo-1.0"})


@app.post("/_admin/mode")
def set_mode():
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("optimized"), bool):
        return jsonify({"error": "optimized (bool) required"}), 400
    with _lock:
        STATE["optimized"] = body["optimized"]
    return jsonify({"optimized": opt()})


def create_app():
    return app


def main():
    port = int(os.environ.get("DEMO_PORT", "5055"))
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
