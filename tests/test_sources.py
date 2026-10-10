"""Parser tests for every job-site adapter, run offline against saved real responses (tests/fixtures).

If a site changes its markup, re-capture its fixture and these tests show exactly what broke.
"""
import json
from pathlib import Path

import pytest

from jobhuntr.crawler import BASE_KEYWORDS, REMOTE_KEYWORDS
from jobhuntr.sources import ADAPTERS, SourceContext

FIXTURES = Path(__file__).parent / "fixtures"
AREA = ["springfield", "fairview", "riverton", "chatham"]


class FakeResponse:
    def __init__(self, body):
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        return json.loads(self.text) if isinstance(self._body, str) else self._body


class FakeHttp:
    """Serves a fixture for any URL containing one of the given keys; records every call."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _serve(self, url, **kw):
        self.calls.append((url, kw.get("params")))
        for key, body in self.routes.items():
            if key in url:
                return FakeResponse(body)
        return FakeResponse("")

    get = post = _serve


def fixture(name):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return json.loads(text) if name.endswith(".json") else text


def ctx(remote=False, keywords=("information",)):
    return SourceContext(area_terms=AREA, include_remote=remote, keywords=list(keywords),
                         remote_keywords=REMOTE_KEYWORDS if remote else [],
                         local_queries=["Springfield", "Fairview"], area_label="Springfield, IL")


def check_jobs(jobs):
    assert jobs, "parser returned no jobs"
    for j in jobs:
        assert j["title"].strip(), j
        assert j["url"].startswith("https://"), j
        assert "<" not in j["title"] and "<" not in j["location"], f"HTML leaked into {j}"


def test_workday():
    src = {"name": "Leidos", "host": "leidos.wd5.myworkdayjobs.com", "tenant": "leidos", "site": "External"}
    http = FakeHttp({"/jobs": fixture("workday_jobs.json")})
    jobs = ADAPTERS["workday"].fetch_jobs(http, src, ctx())
    check_jobs(jobs)
    assert all(j["url"].startswith("https://leidos.wd5.myworkdayjobs.com/en-US/External/job/") for j in jobs)


def test_talentbrew():
    src = {"name": "Example Health", "base": "https://careers.examplehealth.com"}
    jobs = ADAPTERS["talentbrew"].fetch_jobs(FakeHttp({"search-jobs": fixture("talentbrew_results.json")}), src, ctx())
    check_jobs(jobs)
    assert all("/job/" in j["url"] for j in jobs)


def test_oracle():
    src = {"name": "Example University", "host": "example.fa.ocs.oraclecloud.com", "site": "CX_1002"}
    jobs = ADAPTERS["oracle"].fetch_jobs(FakeHttp({"recruitingCEJobRequisitions": fixture("oracle_reqs.json")}), src, ctx())
    check_jobs(jobs)
    assert all("/sites/CX_1002/job/" in j["url"] for j in jobs)


def test_icims():
    src = {"name": "Peraton", "base": "https://careers-peraton.icims.com"}
    jobs = ADAPTERS["icims"].fetch_jobs(FakeHttp({"/jobs/search": fixture("icims_search.html")}), src, ctx())
    check_jobs(jobs)
    assert all("in_iframe" not in j["url"] for j in jobs)


def test_neogov():
    src = {"name": "City of Springfield", "agency": "springfieldil"}
    pages = iter([fixture("neogov_page.html"), ""])  # page 2 is empty -> stop

    class Paged(FakeHttp):
        def _serve(self, url, **kw):
            return FakeResponse(next(pages))
        get = _serve

    jobs = ADAPTERS["neogov"].fetch_jobs(Paged({}), src, ctx())
    check_jobs(jobs)
    assert all(j["url"].startswith("https://www.governmentjobs.com/careers/springfieldil/jobs/") for j in jobs)


def test_jibe_includes_descriptions():
    src = {"name": "Example Grocer", "base": "https://careers.example.com"}
    jobs = ADAPTERS["jibe"].fetch_jobs(FakeHttp({"/api/jobs": fixture("jibe_jobs.json")}), src, ctx())
    check_jobs(jobs)
    assert all(j["prefetched"]["text"] for j in jobs), "Jibe jobs should carry their description"


def test_taleo():
    src = {"name": "Example Energy", "host": "exampleenergy.taleo.net", "section": "2", "portal": "101430233"}
    http = FakeHttp({"searchjobs": fixture("taleo_search.json")})
    jobs = ADAPTERS["taleo"].fetch_jobs(http, src, ctx())
    check_jobs(jobs)
    assert all("jobdetail.ftl?job=" in j["url"] for j in jobs)
    assert all("springfield" in j["location"].lower() for j in jobs)


@pytest.mark.parametrize("loc,expected", [
    ("Springfield, IL", "local"),
    ("US-IL-Springfield | US-VA-Falls Church", "local"),
    ("Remote, US", "remote"),
    ("IND-Work from Home-Remote", None),          # India remote is not US remote
    ("4 Locations", "multi"),
    ("Chicago, IL", None),
])
def test_location_rules(loc, expected):
    assert SourceContext(area_terms=AREA, include_remote=True).where(loc) == expected


def test_remote_off_drops_remote():
    assert SourceContext(area_terms=AREA, include_remote=False).where("Remote, US") is None


def test_every_registered_adapter_is_tested():
    tested = {"workday", "talentbrew", "oracle", "icims", "neogov", "jibe", "taleo"}
    assert set(ADAPTERS) - {"usajobs"} == tested, "add a fixture test for the new adapter"


def test_keywords_cover_base_terms():
    assert "help desk" in BASE_KEYWORDS and "forensic" in BASE_KEYWORDS


def test_jibe_details_found_by_requisition_search():
    src = {"name": "Example Grocer", "base": "https://careers.example.com"}
    feed = fixture("jibe_jobs.json")
    req = feed["jobs"][0]["data"]["req_id"]
    http = FakeHttp({"/api/jobs": feed})
    d = ADAPTERS["jibe"].fetch_details(http, src, f"https://careers.example.com/jobs/{req}")
    assert d["text"]
    assert http.calls[-1][1] == {"keywords": req}  # no call to the non-existent /api/jobs/<id>


def test_prefetched_description_is_analyzed_without_refetch(tmp_path):
    from jobhuntr.crawler import Crawler
    from jobhuntr.db import Database
    db = Database(tmp_path / "t.db")
    src = {"name": "Example Grocer", "type": "jibe", "category": "Private"}
    job = {"title": "Help Desk Analyst", "url": "https://careers.example.com/jobs/1", "location": "Springfield, IL",
           "posted": "", "extra": "", "prefetched": {"text": "Requires Security+ and Active Directory.", "contact_name": "", "contact_email": ""}}
    db.upsert_jobs(src, [job], "2026-10-09 10:00:00")
    stored = db._one("SELECT * FROM jobs")
    facts = Crawler(db).fetch_details_for(stored)  # would raise if it tried the network (no such source configured)
    assert "Security+" in facts["certs"] and "Active Directory" in facts["skills"]


def test_no_area_means_nothing_is_local():
    c = SourceContext(area_terms=[], include_remote=False)
    assert c.where("Anywhere, USA") is None and c.where("Springfield, IL") is None


def test_workday_searches_the_users_places():
    src = {"name": "X", "host": "x.wd1.myworkdayjobs.com", "tenant": "x", "site": "External"}
    http = FakeHttp({"/jobs": {"total": 0, "jobPostings": []}})
    ADAPTERS["workday"].fetch_jobs(http, src, ctx())
    assert [kw for _, kw in http.calls] == [None, None]  # POST bodies aren't recorded as params
    assert len(http.calls) == 2  # one query per configured place


def test_region_helpers():
    from jobhuntr import region
    area = region.normalize({"city": " Denver ", "state": "co", "nearby": "Aurora, Lakewood, , Buckley SFB"})
    assert area["city"] == "Denver" and area["state"] == "CO" and area["nearby"] == ["Aurora", "Lakewood", "Buckley SFB"]
    assert region.label(area) == "Denver, CO"
    assert "denver, colorado" in region.area_terms(area) and "aurora" in region.area_terms(area)
    assert region.search_places(area) == ["Denver", "Aurora", "Lakewood", "Buckley SFB"]
    assert region.render_link("https://x.test/?l={place}&r={radius}", area) == "https://x.test/?l=Denver%2C%20CO&r=50"
    assert region.normalize({"city": ""}) is None
