"""Radancy TalentBrew career sites (careers.example.com/search-jobs) via their AJAX results endpoint."""
import re

from .base import details, make_job, strip_tags

PER_PAGE = 100


def _search(http, src, keywords, page):
    params = {"ActiveFacetID": 0, "CurrentPage": page, "RecordsPerPage": PER_PAGE, "Keywords": keywords,
              "Location": "", "SearchResultsModuleName": "Search Results",
              "SearchFiltersModuleName": "Search Filters", "SortCriteria": 0, "SortDirection": 0, "SearchType": 5}
    return http.get(src["base"] + "/search-jobs/results", params=params,
                    headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}).json().get("results", "")


def fetch_jobs(http, src, ctx):
    # Local-only sites can be pulled whole; national systems are searched per keyword.
    queries = [""] if src.get("fetch_all") else ctx.keywords
    max_pages = 30 if src.get("fetch_all") else 3
    out = []
    for kw in queries:
        for page in range(1, max_pages + 1):
            html = _search(http, src, kw, page)
            items = list(re.finditer(r'<a[^>]+href="(/job/[^"]+)"[^>]*>(.*?)</a>', html, re.S))
            for m in items:
                inner = m.group(2)
                t = re.search(r"<h[23][^>]*>(.*?)</h[23]>", inner, re.S)
                title = strip_tags(t.group(1) if t else inner)
                lm = re.search(r'job-location[^>]*>(.*?)</span>', inner, re.S)
                loc = strip_tags(lm.group(1)) if lm else m.group(1).split("/")[2].replace("-", " ").title()
                if "remote" in title.lower() and "remote" not in loc.lower():
                    loc += " (Remote)"
                fac = re.search(r'job-facility[^>]*>(.*?)</span>', inner, re.S)
                if ctx.where(loc) in ("local", "remote"):
                    out.append(make_job(title, src["base"] + m.group(1), loc,
                                        extra=strip_tags(fac.group(1)) if fac else ""))
            if len(items) < PER_PAGE:
                break
    return out


def fetch_details(http, src, url):
    page = http.get(url).text
    i = page.find("ats-description")
    chunk = page[i:i + 40000] if i >= 0 else page
    text = strip_tags(chunk.split(">", 1)[-1])
    text = re.split(r"Sign up to (?:receive|learn)|Sign Up for job alerts|Apply Now\s*\n.*Save Job", text)[0]
    return details(text[:15000])
