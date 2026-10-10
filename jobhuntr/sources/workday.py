"""Workday career sites (https://TENANT.wdN.myworkdayjobs.com/SITE) via their public JSON API."""
import re

from .base import details, make_job, strip_tags

PAGE = 20


def _api(src):
    return f"https://{src['host']}/wday/cxs/{src['tenant']}/{src['site']}"


def fetch_jobs(http, src, ctx):
    queries = [(q, True) for q in ctx.local_queries]
    if ctx.include_remote:
        queries += [(f"remote {k}", False) for k in ctx.remote_keywords]
    out = []
    for query, local in queries:
        offset, total = 0, None
        while True:
            data = http.post(_api(src) + "/jobs", headers={"Accept": "application/json"},
                             json={"appliedFacets": {}, "limit": PAGE, "offset": offset, "searchText": query}).json()
            if total is None:  # Workday only reports the total on the first page
                total = data.get("total", 0)
            posts = data.get("jobPostings", [])
            for p in posts:
                loc = p.get("locationsText", "")
                where = ctx.where(loc)
                if where is None or (where == "multi" and not local):
                    continue
                if where == "multi":
                    loc += f" (incl. {ctx.area_label} area)"
                out.append(make_job(p.get("title"), f"https://{src['host']}/en-US/{src['site']}{p.get('externalPath', '')}",
                                    loc, p.get("postedOn", "")))
            offset += PAGE
            if not posts or offset >= min(total, 400 if local else 40):
                break
    return out


def fetch_details(http, src, url):
    path = re.sub(r"^https://[^/]+/(?:en-US/)?[^/]+", "", url)
    info = http.get(_api(src) + path, headers={"Accept": "application/json"}).json().get("jobPostingInfo", {})
    return details(strip_tags(info.get("jobDescription", "")))
