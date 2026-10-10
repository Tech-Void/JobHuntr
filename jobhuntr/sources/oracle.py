"""Oracle Cloud HCM candidate-experience sites via the public recruiting REST API."""
from .base import details, make_job, strip_tags

PAGE = 200


def _base(src):
    return f"https://{src['host']}/hcmRestApi/resources/latest"


def fetch_jobs(http, src, ctx):
    out, offset = [], 0
    while True:
        finder = f"findReqs;siteNumber={src['site']},limit={PAGE},sortBy=POSTING_DATES_DESC,offset={offset}"
        data = http.get(_base(src) + "/recruitingCEJobRequisitions",
                        params={"onlyData": "true", "expand": "requisitionList.secondaryLocations", "finder": finder}).json()
        item = (data.get("items") or [{}])[0]
        reqs = item.get("requisitionList", [])
        for r in reqs:
            locs = [r.get("PrimaryLocation", "")] + [s.get("Name", "") for s in r.get("secondaryLocations") or []]
            loc = " | ".join(x for x in locs if x)
            if "remote" in (r.get("WorkplaceType") or "").lower():
                loc += " (Remote)"
            if ctx.where(loc):
                out.append(make_job(r.get("Title"),
                                    f"https://{src['host']}/hcmUI/CandidateExperience/en/sites/{src['site']}/job/{r['Id']}",
                                    loc, r.get("PostedDate", "")))
        offset += PAGE
        if not reqs or offset >= item.get("TotalJobsCount", 0) or offset > 3000:
            break
    return out


def fetch_details(http, src, url):
    req_id = url.rstrip("/").rsplit("/", 1)[-1]
    data = http.get(_base(src) + "/recruitingCEJobRequisitionDetails",
                    params={"expand": "all", "onlyData": "true",
                            "finder": f'ById;Id="{req_id}",siteNumber={src["site"]}'}).json()
    it = (data.get("items") or [{}])[0]
    text = "\n".join(strip_tags(it.get(k) or "") for k in
                     ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr"))
    return details(text, it.get("ExternalContactName"), it.get("ExternalContactEmail"))
