"""USAJobs official search API (needs a free key from developer.usajobs.gov)."""
from .base import details, make_job, strip_tags

API = "https://data.usajobs.gov/api/search"


class MissingKey(RuntimeError):
    pass


def _headers(src):
    if not src.get("api_key") or not src.get("email"):
        raise MissingKey("Add your free USAJobs API key + email in Settings to search federal jobs (VA, military bases, agencies)")
    return {"Host": "data.usajobs.gov", "User-Agent": src["email"], "Authorization-Key": src["api_key"]}


def fetch_jobs(http, src, ctx):
    hdr = _headers(src)
    scopes = [{"LocationName": src.get("location") or ctx.area_label, "Radius": src.get("radius_miles", 50)}]
    if ctx.include_remote:
        scopes.append({"RemoteIndicator": "True"})
    out = []
    for scope in scopes:
        for kw in ctx.keywords + ["__2210__"]:
            params = dict(scope, ResultsPerPage=500)
            if kw == "__2210__":
                params["JobCategoryCode"] = "2210"  # IT Management series
            else:
                params["Keyword"] = kw
            for item in http.get(API, params=params, headers=hdr).json().get("SearchResult", {}).get("SearchResultItems", []):
                m = item["MatchedObjectDescriptor"]
                det = (m.get("UserArea") or {}).get("Details") or {}
                grade = f"GS {det.get('LowGrade')}-{det.get('HighGrade')}" if det.get("LowGrade") else ""
                loc = m.get("PositionLocationDisplay", "") + (" (Remote)" if "RemoteIndicator" in scope else "")
                job = make_job(m.get("PositionTitle"), m.get("PositionURI"), loc,
                               (m.get("PublicationStartDate") or "")[:10],
                               " · ".join(x for x in (m.get("DepartmentName"), grade) if x))
                job["company"] = m.get("OrganizationName") or "Federal Government"
                job["prefetched"] = details("\n".join(x for x in (
                    det.get("JobSummary"), " ".join(det.get("MajorDuties") or []),
                    m.get("QualificationSummary"), f"Security clearance: {det.get('SecurityClearance', '')}") if x))
                out.append(job)
    return out


def fetch_details(http, src, url):
    page = http.get(url).text
    i = page.find("Summary")
    return details(strip_tags(page[i:] if i >= 0 else page)[:15000])
