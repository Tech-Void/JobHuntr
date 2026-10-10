"""Skill matching, duplicate grouping, and the Flask API end to end (on a temporary database)."""
import pytest

from jobhuntr import skills
from jobhuntr.crawler import Crawler
from jobhuntr.db import Database
from jobhuntr.matching import group_similar
from jobhuntr.web import create_app


def test_find_skills_and_powershell_is_not_bash():
    found = skills.find_skills("PowerShell scripting, Active Directory, Splunk dashboards, Cisco switching")
    assert {"PowerShell", "Active Directory", "Splunk", "Cisco"} <= set(found)
    assert "Bash / shell scripting" not in found


def test_match_scoring():
    m = skills.match(["Splunk", "Active Directory", "Python", "AWS"], ["Splunk", "Python"])
    assert m["have"] == ["Splunk", "Python"] and m["missing"] == ["Active Directory", "AWS"]
    assert m["score"] == 50  # (2+1)/(4+2)
    assert skills.match(["Splunk"], ["Splunk"]) is None  # too few skills to judge


def test_group_similar_collapses_reposts():
    base = {"company": "Leidos", "location": "Springfield, IL", "first_seen": "2026-10-01", "facts": None}
    jobs = [{**base, "id": i, "url": f"u{i}", "title": f"Python Developer R10{i}2345"} for i in range(4)]
    jobs.append({**base, "id": 9, "url": "u9", "title": "Network Administrator"})
    grouped = group_similar(jobs)
    assert len(grouped) == 2
    dev = next(g for g in grouped if "Python" in g["title"])
    assert len(dev["similar"]) == 3


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNTR_DATA", str(tmp_path))  # never read the developer's real data or personal pack
    db = Database(tmp_path / "t.db")
    app = create_app(db, Crawler(db))
    app.testing = True
    with app.test_client() as c:
        yield c, db


def test_api_tracker_flow(client):
    c, db = client
    r = c.post("/api/jobs/manual", json={"title": "SOC Analyst", "company": "Acme", "status": "applied"})
    job_id = r.get_json()["id"]
    assert c.post(f"/api/jobs/{job_id}/status", json={"status": "interviewing", "note": "phone screen"}).status_code == 200
    assert c.post(f"/api/jobs/{job_id}/interview", json={"at": "2026-10-20T14:30"}).status_code == 200
    ics = c.get(f"/api/jobs/{job_id}/interview.ics")
    assert ics.status_code == 200 and b"DTSTART:20261020T143000" in ics.data
    t = c.get("/api/tracker").get_json()
    assert t["stats"]["by_status"] == {"interviewing": 1}
    assert t["stats"]["response_rate"] == 100
    assert c.post(f"/api/jobs/{job_id}/status", json={"status": "bogus"}).status_code == 400


def test_api_profile_and_searches(client):
    c, _ = client
    p = c.post("/api/profile", json={"resume_text": "Help desk, Active Directory, PowerShell", "extra": "Splunk"}).get_json()
    assert {"Active Directory", "PowerShell", "Splunk", "Help desk / ticketing"} <= set(p["skills"])
    names = [s["name"] for s in c.get("/api/searches").get_json()]
    assert "IT / Cyber / Sysadmin" in names
    sid = c.post("/api/searches", json={"name": "SOC", "keywords": ["soc"]}).get_json()["id"]
    assert c.get(f"/api/jobs?search={sid}").status_code == 200
    assert c.get("/api/jobs?search=99999").status_code == 404


def test_api_insights_and_tailor_without_key(client):
    c, _ = client
    assert set(c.get("/api/insights").get_json()) >= {"weeks", "funnel", "pay", "skills"}
    job_id = c.post("/api/jobs/manual", json={"title": "IT Tech", "company": "Acme"}).get_json()["id"]
    r = c.post(f"/api/jobs/{job_id}/tailor", json={"task": "cover_letter"})
    assert r.status_code == 400 and "API key" in r.get_json()["error"]


def test_api_region_and_crawl_guard(client):
    c, _ = client
    assert c.get("/api/settings").get_json()["region"] is None
    assert c.post("/api/settings", json={"region": {"city": ""}}).status_code == 400
    assert c.post("/api/settings", json={"region": {"city": "Denver", "state": "ZZ"}}).status_code == 400
    assert c.post("/api/settings", json={"region": {"city": "Denver", "state": "CO", "nearby": "Aurora"}}).status_code == 200
    st = c.get("/api/settings").get_json()
    assert st["region"]["label"] == "Denver, CO"
    links = {link["name"]: link["url"] for link in st["manual_links"]}
    assert all("{" not in u for u in links.values()) and any("Denver" in u for u in links.values())
