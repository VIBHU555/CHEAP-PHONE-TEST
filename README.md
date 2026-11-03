# PocketTest AI — *Test for Everyone. Build for Every Device.*

HackFront India · **The Cheap Phone Test** · AI · Developer Tools · Software Testing · Performance Engineering

PocketTest AI runs reproducible browser workflows against a web app under **emulated** constrained conditions (bandwidth, latency, CPU
slowdown, simulated request loss), records real measurements, classifies problems with transparent rules, writes an evidence-based
diagnostic report, stores every run, and compares runs before/after a fix.

> **Scope, stated plainly.** Everything is measured in headless desktop Chromium on your machine. Profiles are example test
> configurations, not benchmarks of any real phone or network. Packet loss is *simulated* and always labelled so. RAM, battery and
> real-device crashes are **not** measured. See [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

## What is in the box
| Path | Contents |
|---|---|
| `backend/` | Flask API, Playwright engine, rules classifier, report generator, comparison, SQLite repository (`schema.sql`) |
| `frontend/` | 8-page dashboard (ES modules, no build step) |
| `demo-app/` | "PocketShop" — local target with deliberate, reproducible faults and an optimisation switch |
| `tests/` | 75 automated test cases (unittest + Node + Playwright) |
| `scripts/` | dev server control, demo-scenario runner, screenshot + video capture |
| `docs/` | architecture, API, testing report, limitations, screenshots, real scenario results |
| `presentation/`, `video/` | PowerPoint deck and demo video (+ scripts/plan) |

## Requirements
Python 3.10+ · Node 18+ (only for the frontend unit tests) · Chromium for Playwright.

## Install
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Run
```bash
# terminal 1 – the demo target (http://127.0.0.1:5055)
python demo-app/server.py
# terminal 2 – PocketTest AI (http://127.0.0.1:8000)
python backend/run_server.py
```
(or `scripts/dev_servers.sh start` on Linux/macOS). Open **http://127.0.0.1:8000**.

### Demo workflow (the 10 steps from the brief)
1. Open PocketTest AI → **New Test**.
2. Target *PocketShop*, profile **Standard Network**, workflow **Shop checkout journey**, 3 repetitions → *Start*.
3. Watch **Test Execution**, then inspect **Test Results** (real timings, requests, JS errors).
4. Run again with **Constrained Network**; compare how the home page, `/api/products`, and findings change.
5. Open the **AI Diagnostic Report** — observations vs. hypotheses, evidence, reproduction steps.
6. Click **Apply sample optimization to demo app**, re-run the *same* profile, then **Run Comparison**.

Or script all of it: `python scripts/run_demo_scenario.py` (writes `docs/demo-scenario-results.json`).

## Tests
```bash
python -m unittest discover -s tests -v          # 68 unittest tests (67 + 1 Node wrapper); ~60 s; needs Chromium
PT_SKIP_BROWSER=1 python -m unittest discover -s tests   # logic/API tests only, no browser
node --test tests/frontend/util.test.mjs         # frontend unit tests (also run by the suite)
# pytest also works:  pip install pytest && pytest tests
```
Results and caveats: [`docs/TESTING_REPORT.md`](docs/TESTING_REPORT.md).

## Optional LLM explanations
`export ANTHROPIC_API_KEY=...` before starting the backend, then use **Add LLM explanations** on a report. Without a key the app is fully
usable and reports are generated deterministically. The key stays server-side. *The live API call has not been exercised in the build
environment* — see limitations.

## Configuration (env vars, see `.env.example`)
`POCKETTEST_PORT`, `POCKETTEST_DB`, `POCKETTEST_MAX_CONCURRENT`, `POCKETTEST_DEMO_URL`, `POCKETTEST_ALLOWED_TARGETS` (extra authorised
origins), `DEMO_PORT`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`.

## Network-shaping requirements
None beyond Chromium: conditions are applied via the DevTools protocol (no root). If you later want OS-level shaping (`tc netem`, a
proxy), it needs elevated privileges; until then the Standard profile + DevTools profiles remain the safe default.

## Security summary
Registered targets only; metadata/link-local/credentialed/unregistered URLs rejected; in-browser origin guard; no shell construction; secrets
via env only; concurrency/size/time limits; CSV formula-injection guard; XSS-tested UI; **no authentication — bind to localhost only**.

## Documentation
[`ARCHITECTURE`](docs/ARCHITECTURE.md) · [`API`](docs/API.md) · [`TESTING_REPORT`](docs/TESTING_REPORT.md) · [`LIMITATIONS`](docs/LIMITATIONS.md) ·
[`VIDEO`](docs/VIDEO.md) · [`SUBMISSION_CHECKLIST`](docs/SUBMISSION_CHECKLIST.md)

## License
MIT — see `LICENSE`. Team details are placeholders: **[TEAM NAME] · [MEMBER NAMES]**.
