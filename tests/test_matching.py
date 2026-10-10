from jobhuntr.matching import Search, classify_it, level_tags


def job(title, category="Private", description=""):
    return {"title": title, "category": category, "description": description}


def test_it_profile_tracks():
    assert classify_it("Help Desk Support Specialist")[0] == "IT Support"
    assert classify_it("Windows Server Administrator - Night Shift")[0] == "Sysadmin / Infrastructure"
    assert classify_it("Vulnerability Analyst")[0] == "Cybersecurity"
    assert classify_it("Digital Forensics Examiner")[0] == "Forensics / DFIR"


def test_it_profile_rejects_lookalikes():
    for title in ["Registered Nurse - ICU", "Security Officer", "Financial Analyst Senior - Technology",
                  "AICC Telecommunicator I", "Combat Systems Engineer II", "Director, Quality Assurance- (Non-IT)"]:
        assert classify_it(title) is None, title


def test_information_security_officer_is_not_a_guard():
    assert classify_it("Information Security Officer")[0] == "Cybersecurity"


def test_level_tags():
    assert level_tags("Senior Network Engineer")[1] == ["Senior"]
    assert level_tags("Network Engineer I")[1] == ["Entry/Mid"]
    assert "Clearance" in level_tags("Help Desk Tech - TS/SCI")[1]


def test_keyword_search_and_exclude():
    s = Search({"id": 1, "name": "SOC", "mode": "keywords", "keywords": ["soc", "splunk"], "exclude": ["manager"]})
    assert s.match(job("SOC Analyst Tier 1"))
    assert not s.match(job("SOC Manager"))
    assert not s.match(job("Social Worker"))  # whole-word matching


def test_description_search_is_opt_in():
    row = {"id": 1, "name": "x", "mode": "keywords", "keywords": ["splunk"]}
    j = job("Security Analyst", description="Experience with Splunk required")
    assert not Search(row).match(j)
    assert Search({**row, "search_descriptions": True}).match(j)


def test_category_filter():
    s = Search({"id": 1, "name": "x", "mode": "it", "categories": ["Hospital"]})
    assert s.match(job("Help Desk Technician", "Hospital"))
    assert not s.match(job("Help Desk Technician", "Private"))
