"""Oracle Taleo career sections (COMPANY.taleo.net/careersection/N) via the job board REST endpoint."""
import json
import re
from urllib.parse import unquote

from .base import details, make_job, strip_tags

FILTERS = ["ORGANIZATION", "LOCATION", "JOB_FIELD", "URGENT_JOB", "EMPLOYEE_STATUS", "STUDY_LEVEL", "JOB_SHIFT"]


def _body(page):
    return {
        "multilineEnabled": False,
        "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
        "fieldData": {"fields": {"KEYWORD": "", "LOCATION": ""}, "valid": True},
        "filterSelectionParam": {"searchFilterSelections": [{"id": f, "selectedValues": []}
                                                            for f in ("POSTING_DATE", "LOCATION", "JOB_FIELD")]},
        "advancedSearchFiltersSelectionParam": {"searchFilterSelections": [{"id": f, "selectedValues": []} for f in FILTERS]},
        "pageNo": page,
    }


def fetch_jobs(http, src, ctx):
    base = f"https://{src['host']}/careersection"
    http.get(f"{base}/{src['section']}/jobsearch.ftl?lang=en")  # sets the session cookies the REST call expects
    out, page = [], 1
    while True:
        data = http.post(f"{base}/rest/jobboard/searchjobs?lang=en&portal={src['portal']}", json=_body(page),
                         headers={"Content-Type": "application/json", "tz": "GMT-05:00",
                                  "tzname": "America/Chicago"}).json()
        reqs = data.get("requisitionList", [])
        for r in reqs:
            cols = r.get("column", [])
            title = cols[0] if cols else ""
            try:
                loc = ", ".join(json.loads(cols[1])) if len(cols) > 1 else ""
            except (ValueError, TypeError):
                loc = cols[1] if len(cols) > 1 else ""
            if ctx.where(loc):
                out.append(make_job(title, f"{base}/{src['section']}/jobdetail.ftl?job={r.get('contestNo')}&lang=en",
                                    loc, cols[2] if len(cols) > 2 else ""))
        paging = data.get("pagingData", {})
        if not reqs or page * paging.get("pageSize", 25) >= paging.get("totalCount", 0) or page >= 40:
            break
        page += 1
    return out


def fetch_details(http, src, url):
    page = http.get(url).text
    # Taleo ships the description URL-encoded inside a hidden "initialHistory" field
    m = re.search(r'id="initialHistory"[^>]*value="([^"]*)"', page)
    raw = unquote(m.group(1)).replace("!|!", "\n") if m else page
    return details(strip_tags(raw)[:15000])
