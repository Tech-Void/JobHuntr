"""iCIMS career portals (careers-COMPANY.icims.com) by scraping the iframe search results."""
import re

from ..http_client import SHORT_USER_AGENT
from .base import details, make_job, strip_tags

# iCIMS' CloudFront WAF rejects the full Chrome UA string but accepts a short one.
HEADERS = {"User-Agent": SHORT_USER_AGENT}


def fetch_jobs(http, src, ctx):
    queries = ctx.local_queries[:3] + (["Remote"] if ctx.include_remote else [])
    out = []
    for q in queries:
        for pr in range(10):
            page = http.get(src["base"] + "/jobs/search", headers=HEADERS,
                            params={"ss": 1, "searchKeyword": q, "in_iframe": 1, "pr": pr}).text
            for card in page.split('class="iCIMS_JobCardItem"')[1:]:
                a = re.search(r'<a href="([^"]+/jobs/\d+/[^"]+)"[^>]*>.*?<h3[^>]*>(.*?)</h3>', card, re.S)
                if not a:
                    continue
                lm = re.search(r'Job Locations</span>\s*<span[^>]*>(.*?)</span>', card, re.S)
                loc = strip_tags(lm.group(1)) if lm else ""
                if loc.strip() in ("US", "USA") or re.search(r"-home\b", loc, re.I):
                    loc += " (Remote/Telework)"
                posted = re.search(r'Posted Date</span>\s*<span title="([^"]+)"', card)
                if ctx.where(loc):
                    url = a.group(1).replace("&amp;", "&").replace("?in_iframe=1", "")
                    out.append(make_job(strip_tags(a.group(2)), url, loc, posted.group(1).split(" ")[0] if posted else ""))
            m = re.search(r"Page \d+ of (\d+)", page)
            if not m or pr + 1 >= int(m.group(1)):
                break
    return out


def fetch_details(http, src, url):
    page = http.get(url + "?in_iframe=1", headers=HEADERS).text
    i = page.find("iCIMS_JobContent")
    return details(strip_tags(page[i:] if i >= 0 else page)[:15000])
