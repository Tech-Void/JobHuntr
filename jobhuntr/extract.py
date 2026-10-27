"""Pull comparable facts out of a job description: recruiter, pay, clearance, certs, experience, degree."""
import re

from . import requirements

# Bump when the rules below change so stored descriptions get re-analyzed on next start.
VERSION = 11

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Phrases that name the hiring contact. Strong cues may give just a name; weak cues need an email nearby
# (job duties often say "serve as the point of contact for...").
STRONG_CUE = re.compile(r"(?:recruiter|talent acquisition (?:partner|specialist|advisor|consultant)|"
                        r"recruiting (?:contact|partner|specialist)|hiring contact|agency contact|hr contact)\s*:?\s*", re.I)
WEAK_CUE = re.compile(r"(?:questions\??,? (?:please )?(?:contact|reach out|email)|for more information,? (?:please )?contact|"
                      r"please contact|point of contact\s*:|contact person\s*:|send (?:your )?resume to|email (?:your )?resume)", re.I)
# Boilerplate that mentions recruiters without naming one
CONTACT_NOISE = re.compile(r"never|fraud|scam|third[- ]party|agenc(?:y|ies)\b(?! contact)|unsolicited|accommodation|"
                           r"disabilit|reasonable|eeo|equal opportunity|privacy|accessibility", re.I)
NAME = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z]\.)?\s[A-Z][a-zA-Z'-]+)\b")
NOT_NAMES = {"Talent Acquisition", "Human Resources", "United States", "Equal Opportunity",
             "Please Contact", "Hiring Manager", "Point Of", "Job Description", "Security Clearance"}

PAY = re.compile(
    r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)\s*([kK])?\s*(?:-|–|—|to)\s*\$?\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)\s*([kK])?"
    r"(?:\s*(?:per|/|an?)\s*(hour|hr|year|yr|annum|annually))?", re.I)

CLEAR_ACTIVE = re.compile(  # word boundaries matter: "concurrent projects" must not read as "current ... TS"
    r"\b(?:active|current|existing|possess(?:ion of)? an?|hold an?|must have an?)\s[^.\n]{0,40}?"
    r"\b(?:secret|ts|top secret|ts/sci|clearance|public trust)\b"
    r"|\b(?:secret|top secret|ts/sci|ts)\s(?:security\s)?clearance\s(?:is\s)?required", re.I)
CLEAR_OBTAIN = re.compile(r"(?:ability|able|eligib\w*|willing(?:ness)?)\s(?:to\s)?(?:obtain|be granted|get)|"
                          r"obtain and maintain|must be able to obtain|clearance eligib|eligible for (?:a )?(?:security )?clearance|"
                          r"background investigation", re.I)
CLEAR_ANY = re.compile(r"clearance|\bsecret\b|ts/sci|public trust|\bpoly", re.I)

CERTS = [
    ("Security+", r"security\s?\+|sec\+|comptia security"), ("Network+", r"network\s?\+"), ("A+", r"\ba\+|comptia a\b"),
    ("CySA+", r"cysa\+?"), ("PenTest+", r"pentest\+"), ("CASP+", r"casp\+?|securityx"), ("Linux+", r"linux\+"),
    ("CCNA", r"\bccna\b"), ("CCNP", r"\bccnp\b"), ("CISSP", r"\bcissp\b"), ("CISM", r"\bcism\b"), ("CISA", r"\bcisa\b"),
    ("CEH", r"\bceh\b|certified ethical hacker"), ("GIAC", r"\bgiac\b|\bgsec\b|\bgcih\b|\bgcfa\b|\bgcfe\b"),
    ("OSCP", r"\boscp\b"), ("ITIL", r"\bitil\b"), ("Azure cert", r"az-\d{3}|azure (?:administrator|fundamentals)"),
    ("AWS cert", r"aws certified"), ("RHCSA", r"\brhcs[ae]\b"), ("EnCE / CFCE", r"\bence\b|\bcfce\b"),
    ("DoD 8140/8570", r"\b8570\b|\b8140\b|\biat (?:level )?i{1,3}\b|\biam level"), ("Epic cert", r"epic certif"),
]
CERTS = [(name, re.compile(p, re.I)) for name, p in CERTS]

YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|to|–)?\s*(?:\d{1,2}\s*)?\+?\s*(?:years?|yrs?)\b[^.\n]{0,60}?experience", re.I)
DEGREES = [("Master's", re.compile(r"master'?s|\bm\.?s\.?\b(?= degree)|\bmba\b", re.I)),
           ("Bachelor's", re.compile(r"bachelor'?s|\bb\.?s\.?\b(?= degree)|\bb\.?a\.?\b(?= degree)|4[- ]year degree|baccalaureate", re.I)),
           ("Associate's", re.compile(r"associate'?s degree|associate of|\baas\b|2[- ]year degree", re.I)),
           ("HS / GED", re.compile(r"high school|\bged\b", re.I))]
EQUIV = re.compile(r"or equivalent|equivalent (?:combination|experience)|in lieu of", re.I)


def _money(num, k):
    v = float(num.replace(",", ""))
    return v * 1000 if k else v


def find_pay(text):
    for m in PAY.finditer(text):
        lo, hi = _money(m.group(1), m.group(2)), _money(m.group(3), m.group(4))
        unit = (m.group(5) or "").lower()
        if hi < lo or hi < 10:
            continue
        hourly = unit in ("hour", "hr") or hi < 200
        if not hourly and hi < 15000:  # skip things like "$500 - $1,000 bonus"
            continue
        if hourly:
            return {"text": f"${lo:,.2f} - ${hi:,.2f}/hr", "annual_mid": round((lo + hi) / 2 * 2080)}
        return {"text": f"${lo:,.0f} - ${hi:,.0f}/yr", "annual_mid": round((lo + hi) / 2)}
    return None


def find_recruiter(text, name="", email=""):
    if name or email:
        return {"name": name, "email": email, "snippet": "Listed as the posting's contact"}
    for strong, cue in ((True, STRONG_CUE), (False, WEAK_CUE)):
        for m in cue.finditer(text):
            window = text[max(0, m.start() - 60):m.end() + 160]
            sentence = " ".join(window.split())
            if CONTACT_NOISE.search(sentence):
                continue
            found_email = EMAIL.search(text[m.start():m.end() + 160])
            # a name must come right after a strong cue ("Recruiter: Jane Smith")
            name = NAME.match(text[m.end():m.end() + 40]) if strong else None
            name = name.group(1) if name and name.group(1) not in NOT_NAMES else ""
            if found_email or name:
                return {"name": name, "email": found_email.group(0) if found_email else "", "snippet": sentence[:220]}
    return None


def find_clearance(text):
    if CLEAR_ACTIVE.search(text):
        return "Active required"
    if CLEAR_ANY.search(text) and CLEAR_OBTAIN.search(text):
        return "Can obtain (sponsored)"
    if CLEAR_ANY.search(text):
        return "Mentioned"
    return "None mentioned"


def find_years(text):
    nums = [int(m.group(1)) for m in YEARS.finditer(text) if int(m.group(1)) <= 25]
    return min(nums) if nums else None


def find_degree(text):
    for name, pat in DEGREES:
        if pat.search(text):
            return name + (" (or equiv. experience)" if EQUIV.search(text) else "")
    return None


def find_workplace(text, location=""):
    blob = f"{location}\n{text[:3000]}".lower()
    if re.search(r"\bhybrid\b", blob):
        return "Hybrid"
    if re.search(r"fully remote|100% remote|remote position|\(remote|remote[,/ ]|telework|work from home", blob):
        return "Remote"
    if re.search(r"on-?site|in[- ]office|onsite", blob):
        return "On-site"
    return None


def analyze(text: str, location: str = "", contact_name: str = "", contact_email: str = "", title: str = "") -> dict:
    text = text or ""
    req = requirements.parse(text, title)
    return {
        "recruiter": find_recruiter(text, contact_name, contact_email),
        "pay": find_pay(text),
        "clearance": find_clearance(text),
        "certs": [name for name, pat in CERTS if pat.search(text)],
        "years": find_years(text),
        "degree": find_degree(text),
        "workplace": find_workplace(text, location),
        "skills": req["skills_all"],
        "req": req,
    }
