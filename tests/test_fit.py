"""Requirement parsing, resume profiling and fit scoring, on synthetic postings and a synthetic resume."""
from jobhuntr import fit, requirements, resume, tailor

RESUME = """Alex Example
IT Support · Systems Administration
PROFESSIONAL SUMMARY
IT technician with 5+ years of hands-on experience supporting a small office.
CORE SKILLS
Support: Tier 1/2 troubleshooting, ticket tracking, printers, Windows 10/11
Systems: Windows Server, Active Directory, VMware, DNS/DHCP, patch management
Tools: Python, Wireshark, Autopsy (lab), AWS (introductory)
PROFESSIONAL EXPERIENCE
IT Specialist | Example Dental | Springfield, IL	Jan 2020 – Present
Provide first-level and escalated support for 40 users, manage Active Directory accounts and permissions.
Deploy patches across all workstations and maintain backup and disaster recovery procedures.
TECHNICAL PROJECTS & LAB WORK
Home lab: Kali Linux and Windows VMs for SOC practice with Splunk.
EDUCATION & CERTIFICATIONS
Associate of Applied Science, Information Technology   May 2024
Bachelor of Applied Technology, Cybersecurity   Expected May 2027
CompTIA A+ (in progress) · CompTIA Security+ (planned)
"""

PROFILE = resume.build_profile(RESUME, "")


def parse(text, title="Job"):
    return requirements.parse(text, title)


# ------------------------------------------------------------------ requirement parsing
def test_years_by_degree_both_word_orders():
    a = parse("Bachelors degree and 5 years of experience or an Associates degree and 7 years of experience "
              "or a High School diploma/equivalent and 9 years of experience.")
    assert a["years_by_degree"] == {3: 5, 2: 7, 1: 9}
    b = parse("5 years with BS/BA or 9 years with a HS Diploma")
    assert b["years_by_degree"] == {3: 5, 1: 9}


def test_years_first_with_in_lieu_tail():
    r = parse("Minimum of 8 years with BS/BA; Minimum of 6 years with MS/MA; 10 years with an AS, 12 years in lieu of a degree")
    assert r["years_by_degree"][2] == 10 and r["years_by_degree"][1] == 12 and r["years_by_degree"][3] == 8


def test_trainable_platform_is_not_a_day_one_blocker():
    r = parse("Requirements:\n3 years of experience with clinical systems\n"
              "Epic certification for assigned modules is required within eighteen (18) months of hire.", "Epic Security Analyst")
    assert "Epic" not in r["specialties"] and "Epic" in r["specialties_title"]
    f = fit.score("Epic Security Analyst", r, PROFILE)
    assert not any("Epic" in b for b in f["blockers"])


def test_degree_substitution_is_not_extra_years():
    r = parse("Bachelor's degree (4 years of comparable experience may be substituted for a degree).")
    assert 3 not in r["years_by_degree"]


def test_overall_years_takes_the_largest_requirement():
    r = parse("Requirements:\n5+ years of experience with VMware vSphere\n5+ years of server management\n"
              "3+ years of experience designing server rooms")
    assert r["years"] == 5


def test_clearance_variants():
    assert parse("Clearance Level Must Currently Possess:\nSecret\nClearance Level Must Be Able to Obtain:\nTop Secret")["clearance"]["active"]
    assert parse("Clearance Level Must Currently Possess:\nNone\nClearance Level Must Be Able to Obtain:\nSecret")["clearance"]["active"] is None
    assert parse("Minimum Clearance Required to Start: TS/SCI")["clearance"]["active"] == "TS/SCI"
    assert parse("Minimum Clearance Required to Start: None")["clearance"]["active"] is None
    assert parse("Secret clearance is required")["clearance"]["active"] == "SECRET"
    assert parse("Must have the ability to obtain and maintain a Secret clearance.")["clearance"]["active"] is None


def test_itil_knowledge_is_not_a_cert():
    assert "ITIL" not in parse("Required: knowledge of ITIL practices across incident and change management.")["certs_required"]
    assert "ITIL" in parse("Required: ITIL Foundation certification.")["certs_required"]


def test_cert_timing():
    assert parse("Must currently possess Security+ CE at start.")["certs_required"]["Security+"] == "now"
    assert parse("Required: Security+ or the ability to obtain within 6 months of hire.")["certs_required"]["Security+"] == "later"


def test_required_vs_preferred_lines():
    r = parse("Minimum Requirements:\nExperience with Active Directory and Windows Server\n"
              "Preferred Qualifications:\nExperience with Splunk")
    assert "Active Directory" in r["skills_required"] and "Splunk" in r["skills_preferred"]


# ------------------------------------------------------------------ resume profile
def test_profile_facts():
    f = PROFILE["facts"]
    assert f["years"] == 5
    assert f["degree"] == 2 and f["degree_in_progress"] == 3
    assert f["certs"] == [] and set(f["certs_in_progress"]) == {"A+", "Security+"}
    assert f["clearance"] == "none"


def test_lab_skills_are_separated():
    assert "AWS" in PROFILE["skills_lab"] and "Digital forensics" in PROFILE["skills_lab"]
    assert "Python" not in PROFILE["skills_lab"] and "Active Directory" not in PROFILE["skills_lab"]


def test_resume_cleanup():
    assert resume.clean_text("Support &amp; Hardware � Example &amp; Co") == "Support & Hardware · Example & Co"


def test_overrides_win():
    p = resume.build_profile(RESUME, "", {"clearance": "secret", "years": 8})
    assert p["facts"]["clearance"] == "secret" and p["facts"]["years"] == 8


# ------------------------------------------------------------------ fit scoring
HELP_DESK = ("Help Desk Technician", "Minimum Requirements:\n2+ years of help desk experience\n"
             "Experience with Active Directory and Windows 10/11\nHigh school diploma required")
PRINCIPAL = ("Principal Systems Engineer", "Requirements:\n12+ years of experience\nActive TS/SCI clearance required\n"
             "Bachelor's degree in computer science required")
TS_ADMIN = ("Windows Server Administrator", "Requirements:\nBachelor's degree and 2+ years of experience with Windows servers.\n"
            "Additional experience may be considered in lieu of degree.\nAn active TS/SCI security clearance is required.\n"
            "Proficient with Active Directory, DNS, DHCP and VMware.")
EPIC = ("Epic Analyst", "Requirements:\n3+ years of Epic analyst experience required\nEpic certification required")


def score(job, profile=PROFILE):
    title, text = job
    return fit.score(title, parse(text, title), profile)


def test_entry_fit_beats_senior_and_blocked_jobs():
    hd, pr, ts = score(HELP_DESK), score(PRINCIPAL), score(TS_ADMIN)
    assert hd["fit"] > ts["fit"] > 0 and hd["fit"] > pr["fit"]
    assert hd["label"] in ("Strong fit", "Good fit")
    assert pr["label"] == "Poor fit"


def test_clearance_blocks_but_skills_still_show():
    ts = score(TS_ADMIN)
    assert any("clearance" in b for b in ts["blockers"])
    assert ts["skill_fit"] >= 60  # skills line up; only the clearance is in the way
    assert any("substitute" in r[1] for r in ts["reasons"])  # experience can replace the bachelor's


def test_holding_the_clearance_removes_the_block():
    cleared = resume.build_profile(RESUME, "", {"clearance": "ts/sci"})
    assert score(TS_ADMIN, cleared)["fit"] > score(TS_ADMIN)["fit"] * 3


def test_niche_platform_is_a_blocker():
    e = score(EPIC)
    assert any("Epic" in b for b in e["blockers"]) and e["fit"] < 30


def test_lab_skill_counts_half():
    job = ("SOC Analyst", "Requirements:\nExperience with Splunk\nExperience with Active Directory")
    r = score(job)
    splunk = next(s for s in r["skills"]["required"] if s["name"] == "Splunk")
    assert splunk == {"name": "Splunk", "have": True, "lab": True}


# ------------------------------------------------------------------ tailoring
def test_tailor_suggestions():
    title, text = TS_ADMIN
    req = parse(text, title)
    out = tailor.suggest(PROFILE, title, text, req, fit.score(title, req, PROFILE))
    assert out["lead"] and "Active Directory" in out["skills_line"]
    assert any("clearance" in g for g in out["gaps"])
    assert all("Alex" not in b["text"] and "@" not in b["text"] for b in out["lead"])  # no contact lines
