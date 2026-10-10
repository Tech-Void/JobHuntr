from jobhuntr import extract


def test_pay_annual_and_hourly():
    assert extract.find_pay("Pay Range: $65,000 - $85,000 per year")["text"] == "$65,000 - $85,000/yr"
    assert extract.find_pay("$22.50 - $28.00 per hour")["annual_mid"] == round(25.25 * 2080)
    assert extract.find_pay("$80k-$95k")["text"] == "$80,000 - $95,000/yr"
    assert extract.find_pay("a $500 - $1,000 referral bonus") is None


def test_clearance_levels():
    assert extract.find_clearance("Must possess an active Secret clearance.") == "Active required"
    assert extract.find_clearance("Ability to obtain and maintain a Secret clearance.") == "Can obtain (sponsored)"
    assert extract.find_clearance("Great benefits and PTO.") == "None mentioned"
    # regression: "concurrent projects" once matched "current ... TS"
    assert extract.find_clearance("Prioritize appropriately on concurrent projects.") == "None mentioned"
    assert extract.find_clearance("Requires an active TS/SCI.") == "Active required"


def test_certs_and_years_and_degree():
    text = ("Requires 2+ years of experience in desktop support. CompTIA Security+ or ability to obtain "
            "within 6 months (DoD 8570 IAT Level II). Bachelor's degree or equivalent experience.")
    facts = extract.analyze(text)
    assert "Security+" in facts["certs"] and "DoD 8140/8570" in facts["certs"]
    assert facts["years"] == 2
    assert facts["degree"] == "Bachelor's (or equiv. experience)"


def test_recruiter_detection():
    r = extract.find_recruiter("Questions? Please contact your recruiter Jane Smith at jane.smith@example.com.")
    assert r and r["email"] == "jane.smith@example.com"
    assert extract.find_recruiter("Our recruiters will never ask you for payment. Beware of recruitment fraud.") is None
    assert extract.find_recruiter("", "Pat Lee", "pat@uth.edu")["name"] == "Pat Lee"
