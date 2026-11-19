"""Start the PocketTest AI backend (serves API + frontend) on http://127.0.0.1:8000"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.server import create_app

if __name__ == "__main__":
    port = int(os.environ.get("POCKETTEST_PORT", "8000"))
    create_app().run(host="127.0.0.1", port=port, threaded=True, debug=False)
