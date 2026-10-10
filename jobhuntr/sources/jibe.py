"""Jibe / iCIMS Talent Cloud career sites (careers.<company>.com/jobs) via their /api/jobs JSON feed.

The feed includes each job's full description, so no second request is needed for details.
"""
from .base import details, make_job, strip_tags

PAGE = 100


def fetch_jobs(http, src, ctx):
    out = {}
    for kw in ctx.keywords:
        for page in range(1, 6):
            data = http.get(src["base"] + "/api/jobs", headers={"Accept": "application/json"},
                            params={"keywords": kw, "page": page, "limit": PAGE}).json()
            jobs = data.get("jobs", [])
            for item in jobs:
                d = item.get("data", {})
                loc = d.get("full_location") or ", ".join(x for x in (d.get("city"), d.get("state")) if x)
                if "remote" in (d.get("title", "") + d.get("location_type", "")).lower() and "remote" not in loc.lower():
                    loc += " (Remote)"
                if not ctx.where(loc) or d.get("req_id") in out:
                    continue
                cats = d.get("category")
                dept = (cats[0] if cats else "") if isinstance(cats, list) else (cats or "")
                job = make_job(d.get("title"), f"{src['base']}/jobs/{d.get('slug') or d.get('req_id')}", loc,
                               (d.get("posted_date") or "")[:10], dept)
                text = "\n".join(strip_tags(d.get(k) or "") for k in ("description", "responsibilities", "qualifications"))
                job["prefetched"] = details(text)
                out[d.get("req_id")] = job
            if len(jobs) < PAGE or page * PAGE >= data.get("totalCount", 0):
                break
    return list(out.values())


def fetch_details(http, src, url):
    # There is no single-job endpoint (/api/jobs/<id> is a 404 page); searching by the requisition id finds it.
    req_id = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    jobs = http.get(src["base"] + "/api/jobs", headers={"Accept": "application/json"},
                    params={"keywords": req_id}).json().get("jobs", [])
    d = next((j["data"] for j in jobs if str(j.get("data", {}).get("req_id")) == req_id), None)
    if not d:
        raise LookupError("posting no longer listed")
    return details("\n".join(strip_tags(d.get(k) or "") for k in ("description", "responsibilities", "qualifications")))
