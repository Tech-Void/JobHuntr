"""Flask app: serves the single-page UI and a small JSON API."""
import csv
import io
import json
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from . import ai, fit, region, requirements, resume, skills, system
from . import tailor as tailoring
from .crawler import Crawler, days_since, load_config, load_pack, parse_workday_url
from .db import STATUSES, Database
from .matching import Search, group_similar, level_tags
from .paths import resource_dir

RESPONDED = {"interviewing", "offer", "rejected"}
WINDOW_FORGET_SECONDS = 12 * 3600


class Lifecycle:
    """Tracks open app windows so the server knows when it's safe to quit."""

    def __init__(self):
        self.last_request = time.time()
        self.ever_connected = False
        self._windows = {}  # client id -> last heartbeat
        self._lock = threading.Lock()

    def hello(self, client):
        with self._lock:
            self._windows[client] = time.time()
            self.ever_connected = True

    def bye(self, client):
        with self._lock:
            self._windows.pop(client, None)

    def open_windows(self):
        cutoff = time.time() - WINDOW_FORGET_SECONDS
        with self._lock:
            self._windows = {c: t for c, t in self._windows.items() if t > cutoff}
            return len(self._windows)


def create_app(db: Database, crawler: Crawler) -> Flask:
    static = resource_dir() / "static"
    app = Flask(__name__, static_folder=str(static), static_url_path="/static")
    life = app.config["lifecycle"] = Lifecycle()

    @app.before_request
    def note_activity():
        life.last_request = time.time()

    def search_or_404(search_id):
        row = next((s for s in db.searches() if s["id"] == search_id), None)
        if not row:
            abort(404, "search not found")
        return Search(row)

    def last_run_start():
        lr = db.get_setting("last_run")
        return lr["started_at"] if lr and len(db.runs(2)) > 1 else None  # nothing is "new" on the first run

    def my_skills():
        return (my_profile() or {}).get("skills") or []

    def my_profile():
        """The saved profile, upgraded in place if it predates structured facts (years, degree, certs...)."""
        p = db.get_setting("profile")
        if p and p.get("resume_text") and ("facts" not in p or p.get("v") != resume.PROFILE_VERSION):
            p = resume.build_profile(p["resume_text"], p.get("extra", ""), p.get("overrides"))
            db.set_setting("profile", p)
        return p if p and p.get("resume_text") else None

    def job_fit(job, facts, prof):
        req = (facts or {}).get("req") or requirements.parse("", job["title"])
        result = fit.score(job["title"], req, prof)
        result["estimated"] = not (facts and facts.get("req"))  # no description read yet: title-only guess
        return result

    def public(job, new_since, prof=None):
        job = dict(job)
        job.pop("description", None)
        job["facts"] = json.loads(job["facts"]) if job.get("facts") else None
        job["is_new"] = bool(new_since and job["first_seen"] >= new_since)
        if prof:
            job["fit"] = job_fit(job, job["facts"], prof)
            if job["facts"]:
                job["facts"].pop("req", None)  # keep list payloads small; the detail view has it
        return job

    # ------------------------------------------------------------------ UI --
    @app.get("/")
    def index():
        return send_from_directory(static, "index.html")

    @app.post("/api/ping")
    def ping():
        life.hello(request.args.get("client", "anon"))
        return {"ok": True}

    @app.post("/api/bye")
    def bye():  # sent with navigator.sendBeacon when a window closes or reloads
        life.bye(request.args.get("client", "anon"))
        return {"ok": True}

    # ---------------------------------------------------------------- jobs --
    @app.get("/api/searches")
    def list_searches():
        new_since = last_run_start()
        rows = db.searches()
        jobs = db.jobs_for_matching(with_description=any(r["search_descriptions"] for r in rows))
        for r in rows:
            s = Search(r)
            hits = [{**j, "is_new": bool(new_since and j["first_seen"] >= new_since)}
                    for j in jobs if j["active"] and not j["hidden"] and s.match(j)]
            hits = group_similar(hits)
            r["count"] = len(hits)
            r["new"] = sum(1 for j in hits if j["is_new"])
        return jsonify(rows)

    @app.post("/api/searches")
    def create_search():
        body = request.get_json(force=True)
        if not body.get("name", "").strip():
            abort(400, "name required")
        return {"id": db.save_search(body)}

    @app.put("/api/searches/<int:search_id>")
    def update_search(search_id):
        body = request.get_json(force=True)
        body["id"] = search_id
        db.save_search(body)
        return {"ok": True}

    @app.delete("/api/searches/<int:search_id>")
    def delete_search(search_id):
        db.delete_search(search_id)
        return {"ok": True}

    @app.get("/api/jobs")
    def list_jobs():
        search = search_or_404(int(request.args.get("search", 0)))
        new_since = last_run_start()
        prof = my_profile()
        out = []
        for j in db.jobs_for_matching(with_description=search.search_descriptions):
            if not j["active"]:
                continue
            m = search.match(j)
            if m:
                out.append({**public(j, new_since, prof), **m})
        return jsonify(group_similar(out))

    @app.get("/api/jobs/<int:job_id>")
    def get_job(job_id):
        job = db.get_job(job_id) or abort(404)
        desc = job.get("description")
        prof = my_profile()
        facts = json.loads(job["facts"]) if job.get("facts") else None
        out = public(job, last_run_start(), prof)
        out["description"] = desc
        if prof and facts and facts.get("req"):
            out["tailor"] = tailoring.suggest(prof, job["title"], desc or "", facts["req"], out["fit"])
        return jsonify(out)

    @app.post("/api/jobs/<int:job_id>/details")
    def load_details(job_id):
        job = db.get_job(job_id) or abort(404)
        try:
            return {"facts": crawler.fetch_details_for(job, quick=True)}
        except Exception as e:  # noqa: BLE001
            db.set_details_error(job_id, str(e))
            return {"error": str(e)}, 502

    @app.post("/api/jobs/<int:job_id>/state")
    def set_state(job_id):
        body = request.get_json(force=True)
        db.update_job_state(job_id, starred=body.get("starred"), hidden=body.get("hidden"), notes=body.get("notes"))
        return {"ok": True}

    @app.post("/api/jobs/<int:job_id>/status")
    def set_status(job_id):
        body = request.get_json(force=True)
        status = body.get("status")
        if status is not None and status not in STATUSES:
            abort(400, "bad status")
        db.set_status(job_id, status, body.get("note", ""))
        return {"ok": True}

    @app.post("/api/jobs/manual")
    def add_manual():
        b = request.get_json(force=True)
        if not b.get("title") or not b.get("company"):
            abort(400, "title and company required")
        job_id = db.add_manual_job(b["title"], b["company"], b.get("url", ""), b.get("location", ""),
                                   b.get("category", "Other"), b.get("status", "applied"), b.get("notes", ""))
        return {"id": job_id}

    # ------------------------------------------------------------- tracker --
    @app.get("/api/tracker")
    def tracker():
        jobs = tracked_with_facts()
        ghost_days = db.get_setting("ghost_days", 21)
        follow_days = db.get_setting("follow_up_days", 7)
        for j in jobs:
            j["days_in_status"] = days_since(j["status_at"])
            waiting = j["status"] == "applied"
            j["suggest_ghosted"] = waiting and (j["days_in_status"] or 0) >= ghost_days
            j["suggest_follow_up"] = (waiting and not j["suggest_ghosted"] and not j["followed_up_at"]
                                      and (days_since(j["applied_at"]) or 0) >= follow_days)
        return jsonify({"jobs": jobs, "stats": tracker_stats(jobs), "ghost_days": ghost_days,
                        "follow_up_days": follow_days})

    def tracked_with_facts():
        jobs = db.tracked_jobs()
        for j in jobs:
            j["facts"] = json.loads(j["facts"]) if j.get("facts") else None
        return jobs

    def tracker_stats(jobs):
        by_status = Counter(j["status"] for j in jobs)
        companies = defaultdict(lambda: {"applied": 0, "responded": 0, "interviewing": 0, "offer": 0, "rejected": 0,
                                         "ghosted": 0, "response_days": []})
        for j in jobs:
            c = companies[j["company"]]
            c["applied"] += 1  # every tracked job counts as an application
            if j["status"] in ("interviewing", "offer", "rejected", "ghosted"):
                c[j["status"]] += 1
            first_reply = next((h for h in j["history"] if h["status"] in RESPONDED), None)
            if first_reply:
                c["responded"] += 1
                c["response_days"].append(days_between(j["applied_at"], first_reply["at"]))
        rows = []
        for name, c in companies.items():
            days = [d for d in c.pop("response_days") if d is not None]
            rows.append({"company": name, **c, "avg_response_days": round(sum(days) / len(days), 1) if days else None})
        rows.sort(key=lambda r: (-r["applied"], r["company"]))
        total = len(jobs)
        responded = sum(1 for j in jobs if any(h["status"] in RESPONDED for h in j["history"]))
        return {"total": total, "by_status": by_status, "response_rate": round(100 * responded / total) if total else 0,
                "companies": rows}

    @app.get("/api/tracker.csv")
    def tracker_csv():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Company", "Title", "Location", "Status", "Applied", "Last update", "URL", "Notes"])
        for j in db.tracked_jobs():
            w.writerow([j["company"], j["title"], j["location"], j["status"], j["applied_at"], j["status_at"],
                        j["url"] if not j["url"].startswith("manual:") else "", j["notes"]])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=jobhuntr-applications.csv"})

    # --------------------------------------------------------------- crawl --
    @app.post("/api/crawl")
    def start_crawl():
        return {"started": crawler.start()}

    @app.get("/api/crawl")
    def crawl_status():
        return jsonify(crawler.status())

    # ------------------------------------------------------------ settings --
    @app.get("/api/settings")
    def get_settings():
        cfg = load_config(db)
        custom = {s["name"] for s in db.get_setting("custom_sources", [])}
        last = db.runs(1)
        last_sources = last[0]["summary"].get("sources", {}) if last else {}
        key = db.get_setting("usajobs", {})
        area = cfg["region"]
        return jsonify({
            "region": {**area, "label": region.label(area), "area_terms": region.area_terms(area)} if area else None,
            "states": region.STATES,
            "pack": {"sources": len(load_pack().get("sources", []))},
            "include_remote": db.get_setting("include_remote", True),
            "ghost_days": db.get_setting("ghost_days", 21),
            "follow_up_days": db.get_setting("follow_up_days", 7),
            "has_ai_key": bool(db.get_setting("ai_key")),
            "usajobs": {"email": key.get("email", ""), "has_key": bool(key.get("api_key"))},
            "sources": [{"name": s["name"], "type": s["type"], "category": s["category"], "enabled": s["enabled"],
                         "custom": s["name"] in custom, "last": last_sources.get(s["name"])} for s in cfg["sources"]],
            "manual_links": cfg["manual_links"],
            "last_run": db.get_setting("last_run"),
        })

    @app.post("/api/settings")
    def save_settings():
        b = request.get_json(force=True)
        if "region" in b:
            area = region.normalize(b["region"])
            if not area:
                abort(400, "Enter the city you're job hunting in")
            if area["state"] and area["state"] not in region.STATES:
                abort(400, "Pick a US state")
            db.set_setting("region", area)
        if "include_remote" in b:
            db.set_setting("include_remote", bool(b["include_remote"]))
        if "ghost_days" in b:
            db.set_setting("ghost_days", max(1, int(b["ghost_days"])))
        if "follow_up_days" in b:
            db.set_setting("follow_up_days", max(1, int(b["follow_up_days"])))
        if "ai_key" in b:
            db.set_setting("ai_key", (b["ai_key"] or "").strip())
        if "usajobs" in b:
            cur = db.get_setting("usajobs", {})
            cur["email"] = b["usajobs"].get("email", cur.get("email", ""))
            if b["usajobs"].get("api_key"):
                cur["api_key"] = b["usajobs"]["api_key"].strip()
            db.set_setting("usajobs", cur)
        return {"ok": True}

    @app.post("/api/sources/toggle")
    def toggle_source():
        b = request.get_json(force=True)
        disabled = set(db.get_setting("disabled_sources", []))
        (disabled.discard if b["enabled"] else disabled.add)(b["name"])
        db.set_setting("disabled_sources", sorted(disabled))
        return {"ok": True}

    @app.post("/api/sources")
    def add_source():
        b = request.get_json(force=True)
        src = parse_workday_url(b.get("url", ""))
        if not src:
            abort(400, "That doesn't look like a Workday careers link (…myworkdayjobs.com/…)")
        src["name"] = b.get("name", "").strip() or src["tenant"].title()
        src["category"] = b.get("category") or "Private"
        try:
            crawler.http.post(f"https://{src['host']}/wday/cxs/{src['tenant']}/{src['site']}/jobs",
                              json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                              headers={"Accept": "application/json"})
        except Exception as e:  # noqa: BLE001
            abort(400, f"Couldn't reach that Workday site: {e}")
        custom = [s for s in db.get_setting("custom_sources", []) if s["name"] != src["name"]]
        db.set_setting("custom_sources", custom + [src])
        return {"ok": True, "source": src}

    @app.delete("/api/sources/<path:name>")
    def delete_source(name):
        db.set_setting("custom_sources", [s for s in db.get_setting("custom_sources", []) if s["name"] != name])
        return {"ok": True}

    # ------------------------------------------------------------- profile --
    @app.get("/api/profile")
    def get_profile():
        return jsonify(my_profile() or resume.build_profile("", ""))

    @app.post("/api/profile")
    def save_profile():
        b = request.get_json(force=True)
        old = db.get_setting("profile") or {}
        overrides = b.get("overrides", old.get("overrides"))
        p = resume.build_profile(b.get("resume_text", old.get("resume_text", "")), b.get("extra", old.get("extra", "")), overrides)
        db.set_setting("profile", p)
        return jsonify(p)

    @app.post("/api/profile/upload")
    def upload_resume():
        f = request.files.get("file")
        if not f:
            abort(400, "No file uploaded")
        try:
            text = resume.text_from_file(f.filename, f.read())
        except Exception as e:  # noqa: BLE001 - corrupt/unsupported files
            abort(400, f"Couldn't read that file: {e}")
        if not text.strip():
            abort(400, "No text found in that file (is it a scanned image?). Paste the text instead.")
        return {"resume_text": text.strip()}

    # ---------------------------------------------------- interviews/follow-ups --
    @app.post("/api/jobs/<int:job_id>/interview")
    def set_interview(job_id):
        db.get_job(job_id) or abort(404)
        when = request.get_json(force=True).get("at")
        if when and not _valid_local_dt(when):
            abort(400, "Use a date and time")
        db.set_interview(job_id, when)
        return {"ok": True}

    @app.post("/api/jobs/<int:job_id>/followed-up")
    def followed_up(job_id):
        db.get_job(job_id) or abort(404)
        db.mark_followed_up(job_id)
        return {"ok": True}

    @app.get("/api/jobs/<int:job_id>/interview.ics")
    def interview_ics(job_id):
        job = db.get_job(job_id) or abort(404)
        if not job.get("interview_at"):
            abort(404, "No interview scheduled")
        start = datetime.strptime(job["interview_at"][:16], "%Y-%m-%dT%H:%M")
        end = start + timedelta(hours=1)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        url = "" if job["url"].startswith("manual:") else job["url"]

        def ics_text(s):
            return (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")
        ics = "\r\n".join([
            "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//JobHuntr//EN", "BEGIN:VEVENT",
            f"UID:jobhuntr-{job_id}-{start:%Y%m%dT%H%M}@jobhuntr", f"DTSTAMP:{stamp}",
            f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{end:%Y%m%dT%H%M%S}",
            f"SUMMARY:{ics_text('Interview: ' + job['title'] + ' - ' + job['company'])}",
            f"DESCRIPTION:{ics_text((job.get('notes') or '') + (chr(10) + url if url else ''))}",
            "BEGIN:VALARM", "TRIGGER:-PT1H", "ACTION:DISPLAY", "DESCRIPTION:Interview in 1 hour", "END:VALARM",
            "END:VEVENT", "END:VCALENDAR", ""])
        return Response(ics, mimetype="text/calendar",
                        headers={"Content-Disposition": f"attachment; filename=interview-{job_id}.ics"})

    # ------------------------------------------------------------ insights --
    @app.get("/api/insights")
    def insights():
        searches = [Search(r) for r in db.searches()]
        mine = set(my_skills())
        matched = []
        for j in db.jobs_for_matching():
            if not j["active"] or j["hidden"]:
                continue
            hit = next((m for s in searches if (m := s.match(j))), None)
            if hit:
                matched.append({**j, "track": hit["track"], "facts": json.loads(j["facts"]) if j["facts"] else None})

        pay = defaultdict(list)
        demand = Counter()
        for j in matched:
            f = j["facts"]
            if not f:
                continue
            if f.get("pay") and "Senior" not in level_tags(j["title"])[1]:  # senior pay would skew the picture
                pay[j["track"]].append(f["pay"]["annual_mid"])
            demand.update(f.get("skills") or [])
        pay_rows = []
        for track, vals in sorted(pay.items()):
            vals.sort()
            pay_rows.append({"track": track, "n": len(vals), "min": vals[0], "max": vals[-1],
                             "median": vals[len(vals) // 2]})

        tracked = db.tracked_jobs()
        weeks = _week_buckets(12)
        apps_per_week = Counter(_week_of(j["applied_at"]) for j in tracked)
        found_per_week = Counter(_week_of(j["first_seen"]) for j in matched)
        responded = sum(1 for j in tracked if any(h["status"] in RESPONDED for h in j["history"]))
        interviewed = sum(1 for j in tracked if any(h["status"] in ("interviewing", "offer") for h in j["history"]))
        return jsonify({
            "weeks": [{"week": w, "applied": apps_per_week.get(w, 0), "found": found_per_week.get(w, 0)} for w in weeks],
            "funnel": {"applied": len(tracked), "responded": responded, "interviewed": interviewed,
                       "offers": sum(1 for j in tracked if j["status"] == "offer")},
            "pay": pay_rows,
            "skills": [{"skill": s, "jobs": n, "have": s in mine, "group": skills.GROUPS.get(s, "")}
                       for s, n in demand.most_common(20)],
            "has_profile": bool(mine),
            "matched_jobs": len(matched),
            "with_details": sum(1 for j in matched if j["facts"]),
        })

    # ------------------------------------------------------------ schedule --
    @app.get("/api/schedule")
    def get_schedule():
        return jsonify(system.schedule_status())

    @app.post("/api/schedule")
    def save_schedule():
        b = request.get_json(force=True)
        try:
            return jsonify(system.set_schedule(bool(b.get("enabled")), b.get("time", "08:00")))
        except (ValueError, RuntimeError) as e:
            abort(400, str(e))

    @app.post("/api/notify-test")
    def notify_test():
        system.notify("JobHuntr", "Notifications are working. You'll see one like this after each daily crawl.")
        return {"ok": True}

    # ------------------------------------------------------------------ AI --
    @app.post("/api/jobs/<int:job_id>/tailor")
    def tailor(job_id):
        job = db.get_job(job_id) or abort(404)
        task = request.get_json(force=True).get("task", "cover_letter")
        if not job.get("description") and job["source_type"] != "manual":
            try:
                crawler.fetch_details_for(job, quick=True)
                job = db.get_job(job_id)
            except Exception:  # noqa: BLE001 - tailor from the title alone if the site is down
                pass
        profile = db.get_setting("profile") or {}
        try:
            text = ai.tailor(db.get_setting("ai_key", ""), task, profile.get("resume_text", ""),
                             profile.get("extra", ""), job, job.get("description") or "")
        except ai.AIError as e:
            return {"error": str(e)}, 400
        return {"text": text}

    @app.errorhandler(400)
    @app.errorhandler(404)
    def bad_request(e):
        return jsonify({"error": e.description}), e.code

    return app


def _valid_local_dt(s):
    try:
        datetime.strptime(s[:16], "%Y-%m-%dT%H:%M")
        return True
    except (TypeError, ValueError):
        return False


def _week_of(ts):
    """Monday of the week a 'YYYY-MM-DD ...' timestamp falls in, as YYYY-MM-DD."""
    try:
        d = datetime.strptime(ts[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def _week_buckets(n):
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return [(monday - timedelta(weeks=i)).strftime("%Y-%m-%d") for i in range(n - 1, -1, -1)]


def days_between(a, b):
    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        return (datetime.strptime(b[:19], fmt) - datetime.strptime(a[:19], fmt)).days
    except (TypeError, ValueError):
        return None
