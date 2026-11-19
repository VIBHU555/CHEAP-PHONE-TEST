"""SQLite repository layer. All SQL lives here so another backend (PostgreSQL) can replace it."""
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = (Path(__file__).resolve().parents[1] / "schema.sql").read_text()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _j(v):
    return None if v is None else json.dumps(v)


def _l(v):
    return None if v is None else json.loads(v)


class Repo:
    def __init__(self, path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._mem = sqlite3.connect(":memory:", check_same_thread=False) if self.path == ":memory:" else None
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        with self._lock:
            c = self._mem or sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            try:
                yield c
                c.commit()
            except Exception:
                c.rollback()
                raise
            finally:
                if not self._mem:
                    c.close()

    # ---- settings
    def get_setting(self, key, default=None):
        with self.conn() as c:
            r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def set_setting(self, key, value):
        with self.conn() as c:
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, json.dumps(value)))

    # ---- runs
    def create_run(self, *, label, target, profile, workflow_id, repetitions, rules, target_meta):
        rid = uuid.uuid4().hex[:12]
        with self.conn() as c:
            c.execute("""INSERT INTO runs(id,label,status,created_at,target_id,target_url,target_meta,profile_id,profile,
                         workflow_id,repetitions,rules,progress) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (rid, label, "queued", now_iso(), target["id"], target["url"], _j(target_meta), profile["id"],
                       _j(profile), workflow_id, repetitions, _j(rules), _j({"events": [], "done": 0, "total": 0})))
        return rid

    def update_run(self, rid, **fields):
        if not fields:
            return
        json_cols = {"target_meta", "profile", "rules", "environment", "progress", "summary"}
        sets, vals = [], []
        for k, v in fields.items():
            sets.append(f"{k}=?")
            vals.append(_j(v) if k in json_cols else v)
        with self.conn() as c:
            c.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id=?", (*vals, rid))

    @staticmethod
    def _run_row(r):
        d = dict(r)
        for k in ("target_meta", "profile", "rules", "environment", "progress", "summary"):
            d[k] = _l(d.get(k))
        return d

    def get_run(self, rid):
        with self.conn() as c:
            r = c.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        return self._run_row(r) if r else None

    def list_runs(self, status=None, verdict=None, date_from=None, date_to=None, profile_id=None, limit=200):
        q, args = "SELECT * FROM runs WHERE 1=1", []
        if status:
            q += " AND status=?"; args.append(status)
        if verdict:
            q += " AND verdict=?"; args.append(verdict)
        if profile_id:
            q += " AND profile_id=?"; args.append(profile_id)
        if date_from:
            q += " AND created_at>=?"; args.append(date_from)
        if date_to:
            q += " AND created_at<=?"; args.append(date_to)
        q += " ORDER BY created_at DESC LIMIT ?"; args.append(int(limit))
        with self.conn() as c:
            rows = c.execute(q, args).fetchall()
        return [self._run_row(r) for r in rows]

    def delete_run(self, rid):
        with self.conn() as c:
            return c.execute("DELETE FROM runs WHERE id=?", (rid,)).rowcount > 0

    def mark_interrupted(self):
        with self.conn() as c:
            c.execute("UPDATE runs SET status='failed', error='Interrupted: server restarted during run', finished_at=? "
                      "WHERE status IN ('queued','running')", (now_iso(),))

    # ---- measurement data
    def add_step(self, rid, rep, s):
        with self.conn() as c:
            c.execute("""INSERT INTO step_results(run_id,repetition,step_id,step_name,core,status,duration_ms,error,pending,started_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""",
                      (rid, rep, s["step_id"], s["step_name"], int(s["core"]), s["status"], s.get("duration_ms"),
                       s.get("error"), _j(s.get("pending")), s.get("started_at")))

    def add_requests(self, rid, rep, step_id, reqs):
        with self.conn() as c:
            c.executemany("""INSERT INTO requests(run_id,repetition,step_id,method,path,resource_type,status,failed,failure_text,
                             simulated_fault,duration_ms,transfer_bytes,server_ms,is_api,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          [(rid, rep, step_id, r["method"], r["path"], r["resource_type"], r.get("status"), int(r["failed"]),
                            r.get("failure_text"), int(r.get("simulated_fault", False)), r.get("duration_ms"),
                            r.get("transfer_bytes"), r.get("server_ms"), int(r["is_api"]), r.get("source", "browser")) for r in reqs])

    def add_page_metric(self, rid, rep, step_id, m):
        with self.conn() as c:
            c.execute("""INSERT INTO page_metrics(run_id,repetition,step_id,path,nav_duration_ms,dom_content_loaded_ms,load_ms,fcp_ms,
                         lcp_ms,resource_count,transfer_bytes,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (rid, rep, step_id, m["path"], m.get("nav_duration_ms"), m.get("dom_content_loaded_ms"), m.get("load_ms"),
                       m.get("fcp_ms"), m.get("lcp_ms"), m.get("resource_count"), m.get("transfer_bytes"), m.get("source", "browser")))

    def add_js_errors(self, rid, rep, step_id, errs):
        with self.conn() as c:
            c.executemany("INSERT INTO js_errors(run_id,repetition,step_id,kind,message) VALUES(?,?,?,?,?)",
                          [(rid, rep, step_id, e["kind"], e["message"][:2000]) for e in errs])

    def replace_findings(self, rid, findings):
        with self.conn() as c:
            c.execute("DELETE FROM findings WHERE run_id=?", (rid,))
            c.executemany("INSERT INTO findings(run_id,rule_id,severity,title,operation,key,evidence,repro) VALUES(?,?,?,?,?,?,?,?)",
                          [(rid, f["rule_id"], f["severity"], f["title"], f["operation"], f["key"], _j(f["evidence"]), _j(f["repro"]))
                           for f in findings])

    def run_data(self, rid):
        """Everything measured for a run, as plain dicts."""
        with self.conn() as c:
            def rows(t, order="id"):
                return [dict(r) for r in c.execute(f"SELECT * FROM {t} WHERE run_id=? ORDER BY {order}", (rid,)).fetchall()]
            steps, reqs, pm, errs, fnd = rows("step_results"), rows("requests"), rows("page_metrics"), rows("js_errors"), rows("findings")
        for s in steps:
            s["pending"] = _l(s["pending"]); s["core"] = bool(s["core"])
        for r in reqs:
            r["failed"] = bool(r["failed"]); r["is_api"] = bool(r["is_api"]); r["simulated_fault"] = bool(r["simulated_fault"])
        for f in fnd:
            f["evidence"] = _l(f["evidence"]); f["repro"] = _l(f["repro"])
        sev = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        fnd.sort(key=lambda f: (sev.get(f["severity"], 9), f["id"]))
        return {"steps": steps, "requests": reqs, "page_metrics": pm, "js_errors": errs, "findings": fnd}

    # ---- reports
    def save_report(self, rid, generator, content):
        with self.conn() as c:
            c.execute("INSERT INTO reports(run_id,generator,created_at,content) VALUES(?,?,?,?) "
                      "ON CONFLICT(run_id) DO UPDATE SET generator=excluded.generator, created_at=excluded.created_at, content=excluded.content",
                      (rid, generator, now_iso(), json.dumps(content)))

    def get_report(self, rid):
        with self.conn() as c:
            r = c.execute("SELECT * FROM reports WHERE run_id=?", (rid,)).fetchone()
        return {"generator": r["generator"], "created_at": r["created_at"], **json.loads(r["content"])} if r else None
