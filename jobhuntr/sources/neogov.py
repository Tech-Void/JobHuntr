"""NEOGOV / GovernmentJobs.com agency pages (cities, counties, utilities)."""
import html
import re

from .base import details, make_job, strip_tags

BASE = "https://www.governmentjobs.com"


def fetch_jobs(http, src, ctx):
    out = []
    for page in range(1, 60):
        text = http.get(BASE + "/careers/home/index", headers={"X-Requested-With": "XMLHttpRequest"},
                        params={"agency": src["agency"], "sort": "PostingDate", "isDescendingSort": "true",
                                "page": page}).text
        items = text.split('class="list-item"')[1:]
        for it in items:
            a = re.search(r'class="item-details-link"[^>]*href="([^"]+)"[^>]*>([^<]+)', it)
            if not a:
                continue
            meta = re.search(r'<ul class="list-meta">(.*?)</ul>', it, re.S)
            closes = re.search(r'list-entry-ends">([^<]+)', it)
            out.append(make_job(html.unescape(a.group(2)), BASE + a.group(1), src.get("location") or ctx.area_label,
                                closes.group(1).strip() if closes else "",
                                " ".join(strip_tags(meta.group(1)).split()) if meta else ""))
        if not items:
            break
    return out


def fetch_details(http, src, url):
    page = http.get(url).text
    i = page.find("details-info")
    return details(strip_tags(page[i:] if i >= 0 else page)[:15000])
