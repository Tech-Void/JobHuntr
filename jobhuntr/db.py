"""SQLite storage for jobs, application tracking, saved searches, crawl runs and settings."""
import json
import sqlite3
import threading
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    source_type TEXT NOT NULL,
    company TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT DEFAULT '',
    posted TEXT DEFAULT '',
    extra TEXT DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active INTEGER DEFAULT 1,
    description TEXT,
    facts TEXT,
    details_at TEXT,
    details_error TEXT,
    starred INTEGER DEFAULT 0,
    hidden INTEGER DEFAULT 0,
    status TEXT,
    applied_at TEXT,
    status_at TEXT,
    notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS jobs_source ON jobs(source);

CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    at TEXT NOT NULL,
    note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'keywords',
    keywords TEXT DEFAULT '[]',
    exclude TEXT DEFAULT '[]',
    categories TEXT DEFAULT '[]',
    search_descriptions INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    new_count INTEGER DEFAULT 0,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

STATUSES = ["applied", "interviewing", "offer", "rejected", "ghosted", "withdrawn"]
DEFAULT_SEARCHES = [
    {"name": "IT / Cyber / Sysadmin", "mode": "it", "keywords": [], "exclude": []},
    {"name": "Digital Forensics", "mode": "keywords",
     "keywords": ["forensic", "forensics", "dfir", "ediscovery", "e-discovery", "incident response",
                  "malware", "digital evidence", "threat hunter", "cyber investigator"], "exclude": []},
]
JSON_COLS = {"keywords", "exclude", "categories"}


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self._migrate()
            if not self.conn.execute("SELECT 1 FROM searches LIMIT 1").fetchone():
                for s in DEFAULT_SEARCHES:
                    self.save_search(s)

    def _migrate(self):
        """Add columns introduced after v1.0 to existing databases."""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(jobs)")}
        for name in ("interview_at", "followed_up_at"):
            if name not in cols:
                self.conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT")
        self.conn.commit()

    # ------------------------------------------------------------- helpers --
    def _all(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def _one(self, sql, args=()):
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    def _exec(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    # ---------------------------------------------------------------- jobs --
    def upsert_jobs(self, source, jobs, seen_at):
        """Insert or refresh crawled jobs. Returns number of brand-new jobs."""
        new = 0
        unique = {j["url"]: j for j in jobs}.values()  # the same posting can come back from several queries
        with self.lock:
            for j in unique:
                existed = self.conn.execute("SELECT 1 FROM jobs WHERE url=?", (j["url"],)).fetchone()
                self.conn.execute(
                    """INSERT INTO jobs (url, source, source_type, company, category, title, location, posted, extra,
                                         first_seen, last_seen, active)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,1)
                       ON CONFLICT(url) DO UPDATE SET last_seen=excluded.last_seen, active=1, title=excluded.title,
                           location=excluded.location, posted=excluded.posted, extra=excluded.extra""",
                    (j["url"], source["name"], source["type"], j.get("company") or source["name"], source["category"],
                     j["title"], j["location"], j["posted"], j["extra"], seen_at, seen_at))
                new += not existed
                pre = j.get("prefetched")
                if pre:
                    self.conn.execute("UPDATE jobs SET description=? WHERE url=? AND description IS NULL",
                                      (pre["text"], j["url"]))
            self.conn.commit()
        return new

    def deactivate_missing(self, source_name, run_started):
        """Mark a source's jobs that weren't seen in this crawl as closed."""
        self._exec("UPDATE jobs SET active=0 WHERE source=? AND last_seen < ? AND source_type != 'manual'",
                   (source_name, run_started))

    def jobs_for_matching(self, with_description=False):
        cols = "id, url, source, company, category, title, location, posted, extra, first_seen, last_seen, active, " \
               "facts, starred, hidden, status, applied_at, status_at, notes, details_at, details_error"
        if with_description:
            cols += ", description"
        return self._all(f"SELECT {cols} FROM jobs WHERE source_type != 'manual' AND (active=1 OR status IS NOT NULL)")

    def get_job(self, job_id):
        return self._one("SELECT * FROM jobs WHERE id=?", (job_id,))

    def set_details(self, job_id, text, facts):
        self._exec("UPDATE jobs SET description=?, facts=?, details_at=?, details_error=NULL WHERE id=?",
                   (text, json.dumps(facts), now(), job_id))

    def set_details_error(self, job_id, error):
        self._exec("UPDATE jobs SET details_error=?, details_at=? WHERE id=?", (error[:300], now(), job_id))

    def reanalyze(self, analyze, version):
        """Re-run fact extraction over stored descriptions after the extraction rules change."""
        # Always analyze stored descriptions that never got facts (e.g. a prefetched feed whose detail
        # fetch failed); re-analyze everything when the extraction rules changed.
        where = "description IS NOT NULL" if self.get_setting("facts_version") != version \
            else "description IS NOT NULL AND facts IS NULL"
        rows = self._all(f"SELECT id, title, description, location, facts FROM jobs WHERE {where}")
        self.reanalyze_progress = {"done": 0, "total": len(rows)}
        for start in range(0, len(rows), 40):
            batch = []
            for r in rows[start:start + 40]:  # analysis runs outside the lock so the API stays responsive
                old = json.loads(r["facts"]) if r["facts"] else {}
                rec = old.get("recruiter") or {}
                # keep contacts that came from structured fields (e.g. Oracle's ExternalContactName)
                structured = rec.get("snippet") == "Listed as the posting's contact"
                facts = analyze(r["description"], r["location"], rec.get("name", "") if structured else "",
                                rec.get("email", "") if structured else "", r["title"])
                batch.append((json.dumps(facts), r["id"]))
            with self.lock:
                self.conn.executemany("UPDATE jobs SET facts=?, details_error=NULL WHERE id=?", batch)
                self.conn.commit()
            self.reanalyze_progress["done"] = start + len(batch)
        self.set_setting("facts_version", version)
        return len(rows)

    def jobs_needing_details(self, ids):
        if not ids:
            return []
        q = ",".join("?" * len(ids))
        return self._all(f"SELECT id, url, source, source_type, location, description FROM jobs "
                         f"WHERE id IN ({q}) AND facts IS NULL AND details_error IS NULL", ids)

    def update_job_state(self, job_id, starred=None, hidden=None, notes=None):
        fields = {k: v for k, v in (("starred", starred), ("hidden", hidden), ("notes", notes)) if v is not None}
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            self._exec(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))

    def set_status(self, job_id, status, note=""):
        """Move a job through the application pipeline (status None = un-track it)."""
        at = now()
        with self.lock:
            if status is None:
                self.conn.execute("UPDATE jobs SET status=NULL, applied_at=NULL, status_at=NULL WHERE id=?", (job_id,))
                self.conn.execute("DELETE FROM status_history WHERE job_id=?", (job_id,))
            else:
                if status not in STATUSES:
                    raise ValueError(f"unknown status {status}")
                self.conn.execute("UPDATE jobs SET status=?, status_at=?, applied_at=COALESCE(applied_at, ?) WHERE id=?",
                                  (status, at, at, job_id))
                self.conn.execute("INSERT INTO status_history (job_id, status, at, note) VALUES (?,?,?,?)",
                                  (job_id, status, at, note))
            self.conn.commit()

    def set_interview(self, job_id, when):
        """when = 'YYYY-MM-DDTHH:MM' from a datetime-local input, or None to clear."""
        self._exec("UPDATE jobs SET interview_at=? WHERE id=?", (when or None, job_id))
        if when:
            self._exec("INSERT INTO status_history (job_id, status, at, note) "
                       "SELECT id, status, ?, ? FROM jobs WHERE id=?",
                       (now(), f"Interview scheduled {when.replace('T', ' ')}", job_id))

    def mark_followed_up(self, job_id):
        at = now()
        self._exec("UPDATE jobs SET followed_up_at=? WHERE id=?", (at, job_id))
        self._exec("INSERT INTO status_history (job_id, status, at, note) SELECT id, status, ?, 'Followed up' "
                   "FROM jobs WHERE id=?", (at, job_id))

    def add_manual_job(self, title, company, url, location, category, status="applied", notes=""):
        at = now()
        url = url or f"manual:{company}:{title}:{at}"
        with self.lock:
            cur = self.conn.execute(
                """INSERT INTO jobs (url, source, source_type, company, category, title, location, first_seen, last_seen,
                                     active, notes) VALUES (?, 'Manual', 'manual', ?, ?, ?, ?, ?, ?, 1, ?)""",
                (url, company, category or "Other", title, location or "", at, at, notes))
            self.conn.commit()
            job_id = cur.lastrowid
        if status:
            self.set_status(job_id, status)
        return job_id

    def tracked_jobs(self):
        jobs = self._all("SELECT id, url, company, category, title, location, active, facts, status, applied_at, "
                         "status_at, notes, starred, interview_at, followed_up_at FROM jobs "
                         "WHERE status IS NOT NULL ORDER BY applied_at DESC")
        hist = self._all("SELECT job_id, status, at, note FROM status_history ORDER BY at")
        by_job = {}
        for h in hist:
            by_job.setdefault(h["job_id"], []).append(h)
        for j in jobs:
            j["history"] = by_job.get(j["id"], [])
        return jobs

    # ------------------------------------------------------------ searches --
    def searches(self):
        rows = self._all("SELECT * FROM searches ORDER BY id")
        for r in rows:
            for c in JSON_COLS:
                r[c] = json.loads(r[c] or "[]")
        return rows

    def save_search(self, s):
        vals = (s["name"], s.get("mode", "keywords"), json.dumps(s.get("keywords", [])), json.dumps(s.get("exclude", [])),
                json.dumps(s.get("categories", [])), int(bool(s.get("search_descriptions"))))
        if s.get("id"):
            self._exec("UPDATE searches SET name=?, mode=?, keywords=?, exclude=?, categories=?, search_descriptions=? "
                       "WHERE id=?", (*vals, s["id"]))
            return s["id"]
        return self._exec("INSERT INTO searches (name, mode, keywords, exclude, categories, search_descriptions, "
                          "created_at) VALUES (?,?,?,?,?,?,?)", (*vals, now())).lastrowid

    def delete_search(self, search_id):
        self._exec("DELETE FROM searches WHERE id=?", (search_id,))

    # ---------------------------------------------------------- runs/settings --
    def start_run(self, started_at):
        return self._exec("INSERT INTO runs (started_at) VALUES (?)", (started_at,)).lastrowid

    def finish_run(self, run_id, new_count, summary):
        self._exec("UPDATE runs SET finished_at=?, new_count=?, summary=? WHERE id=?",
                   (now(), new_count, json.dumps(summary), run_id))

    def runs(self, limit=10):
        rows = self._all("SELECT * FROM runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["summary"] = json.loads(r["summary"] or "{}")
        return rows

    def get_setting(self, key, default=None):
        row = self._one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set_setting(self, key, value):
        self._exec("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, json.dumps(value)))
