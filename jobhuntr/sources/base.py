"""Shared helpers for source adapters.

Every adapter module exposes:
    fetch_jobs(http, src, ctx) -> list[dict]   # dicts built with make_job()
    fetch_details(http, src, url) -> dict      # {"text": str, "contact_name": str, "contact_email": str}
"""
import html
import re
from dataclasses import dataclass, field

NON_US = re.compile(r"^ind\b|\bindia\b|philippines|mexico|canada|\buk\b|united kingdom|costa rica|poland|"
                    r"ireland|germany|australia|singapore|brazil|colombia|argentina|romania|japan|"
                    r"netherlands|hong kong|^gbr\b|^mex\b", re.I)
REMOTE = re.compile(r"remote|virtual|telework|work from home|\bhome\b", re.I)
MULTI = re.compile(r"^\d+ locations$", re.I)


@dataclass
class SourceContext:
    area_terms: list
    area_exclude: list = field(default_factory=list)
    include_remote: bool = True
    keywords: list = field(default_factory=list)          # union of all search keywords
    remote_keywords: list = field(default_factory=list)   # keywords to pair with "remote" queries
    local_queries: list = field(default_factory=list)     # place names to search for (the user's city first)
    area_label: str = "your area"                         # e.g. "Denver, CO", shown in the UI

    def __post_init__(self):
        terms = [t for t in self.area_terms if t.strip()]
        # no area configured -> nothing counts as local (an empty pattern would match everything)
        self._area = re.compile(r"\b(?:%s)\b" % "|".join(map(re.escape, terms)), re.I) if terms else None

    def where(self, location: str):
        """Classify a location string as 'local', 'remote', 'multi' (unknown multi-site) or None."""
        loc = (location or "").lower()
        for x in self.area_exclude:
            loc = loc.replace(x.lower(), "")
        if NON_US.search(loc):
            return None
        if self._area and self._area.search(loc):
            return "local"
        if self.include_remote and REMOTE.search(loc):
            return "remote"
        if MULTI.match(loc.strip()):
            return "multi"
        return None


def strip_tags(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>|</h\d>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def make_job(title, url, location, posted="", extra=""):
    return {"title": " ".join((title or "").split()), "url": url,
            "location": " ".join((location or "").split()), "posted": posted or "", "extra": extra or ""}


def details(text="", contact_name="", contact_email=""):
    return {"text": text, "contact_name": contact_name or "", "contact_email": contact_email or ""}
