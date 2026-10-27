"""Runs a crawl in a background thread: fetch listings from every source, then details for matching jobs."""
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from . import extract, region
from .db import now
from .http_client import Http
from .matching import Search
from .paths import data_dir, resource_dir
from .sources import ADAPTERS, SourceContext
from .sources.usajobs import MissingKey

# Keywords used by sources that can only be searched by keyword (TalentBrew, USAJobs)
BASE_KEYWORDS = ["information technology", "IT support", "help desk", "service desk", "desktop support", "cyber",
                 "cybersecurity", "information security", "security analyst", "network", "systems administrator",
                 "system administrator", "infrastructure", "technician", "forensic", "information systems", "SOC"]
REMOTE_KEYWORDS = ["cyber", "security analyst", "help desk", "IT support", "systems administrator", "network", "forensic"]
MAX_DETAIL_FETCHES = 600
PREFETCHED_TYPES = {"usajobs", "jibe", "manual"}
PACK_FILE = "my_sources.json"
WORKDAY_URL = re.compile(r"https?://(([\w-]+)\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)")


def load_pack():
    """Optional personal source pack (%APPDATA%\\JobHuntr\\my_sources.json): local employers, links and area."""
    path = data_dir() / PACK_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_config(db):
    """Bundled nationwide sources + the personal pack + user-added sources, with the user's area,
    enable/disable choices and API keys applied."""
    cfg = json.loads((resource_dir() / "default_sources.json").read_text(encoding="utf-8"))
    pack = load_pack()
    names = {s["name"] for s in cfg["sources"]}
    cfg["sources"] += [s for s in pack.get("sources", []) if s["name"] not in names]
    cfg["sources"] += db.get_setting("custom_sources", [])
    cfg["area_exclude"] = pack.get("area_exclude", [])

    area = region.normalize(db.get_setting("region") or pack.get("region"))
    cfg["region"] = area
    links = pack.get("manual_links", []) + cfg.get("manual_links", [])
    cfg["manual_links"] = [{**link, "url": region.render_link(link["url"], area)} for link in links] if area \
        else [link for link in links if "{" not in link["url"]]

    disabled = set(db.get_setting("disabled_sources", []))
    key = db.get_setting("usajobs", {})
    for s in cfg["sources"]:
        s["enabled"] = s["name"] not in disabled
        if s["type"] == "usajobs":
            s.update({k: v for k, v in key.items() if v})
            if area:
                s.setdefault("location", region.label(area))
                s.setdefault("radius_miles", area["radius"])
    return cfg


def source_context(cfg, include_remote, keywords, remote_keywords):
    area = cfg["region"]
    return SourceContext(area_terms=region.area_terms(area), area_exclude=cfg.get("area_exclude", []),
                         include_remote=include_remote, keywords=keywords, remote_keywords=remote_keywords,
                         local_queries=region.search_places(area), area_label=region.label(area))


def parse_workday_url(url):
    """Turn a pasted Workday careers URL into a source config, or None."""
    m = WORKDAY_URL.match(url.strip())
    if not m:
        return None
    return {"type": "workday", "host": m.group(1), "tenant": m.group(2), "site": m.group(3)}


def match_any(searches, job):
    return any(s.match(job) for s in searches)


class Crawler:
    def __init__(self, db):
        self.db = db
        self.http = Http()
        self.quick_http = Http(retries=2, timeout=12)  # someone is waiting on the screen for these
        self._thread = None
        self._lock = threading.Lock()
        self.progress = {"running": False}

    # ------------------------------------------------------------- public --
    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._thread = threading.Thread(target=self._run, daemon=True, name="crawl")
            self._thread.start()
            return True

    def status(self):
        return self.progress

    def fetch_details_for(self, job, quick=False):
        """Fetch + analyze one job's description (used by the crawl and by the 'load details' button)."""
        http = self.quick_http if quick else self.http
        # Sources whose feeds include the description (stored at crawl time) don't need a second request
        if job.get("description") and job.get("source_type") in PREFETCHED_TYPES:
            text, name, email = job["description"], "", ""
        else:
            if job["source_type"] == "manual":
                raise ValueError("Manually added jobs have no source to fetch from")
            cfg = load_config(self.db)
            src = next((s for s in cfg["sources"] if s["name"] == job["source"]), None)
            if not src:
                raise ValueError(f"Source '{job['source']}' is no longer configured")
            d = ADAPTERS[src["type"]].fetch_details(http, src, job["url"])
            text, name, email = d["text"], d["contact_name"], d["contact_email"]
        facts = extract.analyze(text, job.get("location", ""), name, email, job.get("title", ""))
        self.db.set_details(job["id"], text, facts)
        return facts

    # ------------------------------------------------------------ the run --
    def _run(self):
        started = now()
        run_id = self.db.start_run(started)
        cfg = load_config(self.db)
        if not cfg["region"]:
            self.progress = {"running": False, "phase": "Done", "finished_at": now(), "new": 0, "sources": {},
                             "error": "Set your area in Sources & settings before crawling"}
            self.db.finish_run(run_id, 0, {"sources": {}, "error": "no area set"})
            return
        sources = [s for s in cfg["sources"] if s["enabled"]]
        searches = [Search(s) for s in self.db.searches()]
        custom_kw = sorted({k for s in searches for k in s.keywords})
        include_remote = self.db.get_setting("include_remote", True)
        ctx = source_context(cfg, include_remote, BASE_KEYWORDS + custom_kw, (REMOTE_KEYWORDS + custom_kw)[:14])
        self.progress = {"running": True, "phase": "Searching job sites", "started_at": started,
                         "sources": {s["name"]: {"state": "waiting"} for s in sources},
                         "details": {"done": 0, "total": 0}}
        new_total = 0

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(self._crawl_source, s, ctx): s for s in sources}
            for f in as_completed(futures):
                src = futures[f]
                try:
                    jobs = f.result()
                    new = self.db.upsert_jobs(src, jobs, started)
                    self.db.deactivate_missing(src["name"], started)
                    new_total += new
                    self.progress["sources"][src["name"]] = {"state": "ok", "count": len(jobs), "new": new}
                except MissingKey as e:
                    self.progress["sources"][src["name"]] = {"state": "skipped", "error": str(e)}
                except Exception as e:  # noqa: BLE001 - one broken site shouldn't stop the crawl
                    self.progress["sources"][src["name"]] = {"state": "error", "error": f"{type(e).__name__}: {e}"[:300]}

        # Details only for jobs that match a saved search (keeps request count sane)
        self.progress["phase"] = "Reading job descriptions"
        matched = [j["id"] for j in self.db.jobs_for_matching() if j["active"] and match_any(searches, j)]
        todo = self.db.jobs_needing_details(matched)[:MAX_DETAIL_FETCHES]
        self.progress["details"] = {"done": 0, "total": len(todo)}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(self.fetch_details_for, j): j for j in todo}
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as e:  # noqa: BLE001
                    self.db.set_details_error(futures[f]["id"], f"{type(e).__name__}: {e}")
                self.progress["details"]["done"] += 1

        summary = {"sources": self.progress["sources"]}
        self.db.finish_run(run_id, new_total, summary)
        self.db.set_setting("last_run", {"started_at": started, "finished_at": now(), "new": new_total})
        self.progress = {"running": False, "phase": "Done", "finished_at": now(), "new": new_total,
                         "sources": self.progress["sources"]}

    def _crawl_source(self, src, ctx):
        self.progress["sources"][src["name"]] = {"state": "running"}
        return ADAPTERS[src["type"]].fetch_jobs(self.http, src, ctx)


def days_since(ts):
    try:
        return (datetime.now() - datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")).days
    except (TypeError, ValueError):
        return None
