"""Read what a posting actually requires: years by degree, clearance, certs, specialty platforms, required
vs preferred skills. Works on the plain-text descriptions JobHuntr stores."""
import re

from . import skills

DEGREES = {"hs": 1, "associate": 2, "bachelor": 3, "master": 4, "phd": 5}
DEGREE_WORDS = [
    ("phd", r"ph\.?\s?d|doctorate"),
    ("master", r"master'?s?|\bm\.?s\.?\b|\bm\.?a\.?\b|\bmba\b|ms/ma|ma/ms"),
    ("bachelor", r"bachelor'?s?|\bb\.?s\.?\b|\bb\.?a\.?\b|bs/ba|ba/bs|baccalaureate|4[- ]year degree|undergraduate degree"),
    ("associate", r"associate'?s?(?= degree| of|\s+(?:and|with|\+)|\b)|\ba\.?a\.?s\.?\b|\ba\.?s\.?\b(?= degree)|(?-i:\bAS\b)(?=,| degree| and)|2[- ]year degree"),
    ("hs", r"high school|\bhs\b|\bged\b|diploma"),
]
DEGREE_RX = [(k, re.compile(p, re.I)) for k, p in DEGREE_WORDS]
NUM = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen)"
WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
           "eleven": 11, "twelve": 12, "fifteen": 15}

PREFERRED = re.compile(r"prefer|desired|nice to have|a plus\b|is a plus|bonus|helpful|ideal(?:ly)?\b|advantage|optional|"
                       r"additional (?:preferred )?skills|desirable", re.I)
REQUIRED = re.compile(r"\brequired\b|\bmust\b|minimum|basic qualifications|you must have|requirements?:|qualifications:|"
                      r"\bneed to have\b|essential", re.I)
BOILERPLATE = re.compile(r"equal opportunity|eeo\b|disabilit|accommodation|veteran|benefits|401\(?k|paid time off|\bpto\b|"
                         r"drug[- ]free|background check|e-verify|pay (?:range|is based)|compensation|salary range|"
                         r"from roles that align|sign up for job alerts|privacy (?:policy|notice)|recruitment fraud|"
                         r"our recruiters will never|we offer a flexible work|ensures risks associated", re.I)
HEADING_REQ = re.compile(r"^(?:basic|minimum|required|must[- ]have|essential)\b.*(?:qualif|requirement|skill|experience)|"
                         r"^qualifications?(?: you must have)?:?$|^requirements?:?$|^what you(?:'ll)? need|^you have:?$", re.I)
HEADING_PREF = re.compile(r"^(?:preferred|desired|additional|nice[- ]to[- ]have|bonus)\b.*(?:qualif|skill|experience|requirement)?|"
                          r"^what sets you apart", re.I)
# Lines that read like qualifications even without a heading ("Experience with...", "Knowledge of...", "5+ years...")
QUAL_START = re.compile(r"^(?:\(?\d+\)?\s*)?(?:experience|demonstrated|proven|hands-on|working knowledge|knowledge|familiar|proficien|"
                        r"strong (?:knowledge|understanding|experience)|understanding of|ability to (?!work|lift|travel)|"
                        r"\d{1,2}\+?\s*(?:years|yrs)|(?:one|two|three|four|five|six|seven|eight|ten)\s*(?:\(\d+\)\s*)?years|"
                        r"(?:a |an )?(?:bachelor|associate|master|high school|ba/bs|bs/ba|degree)|current(?:ly)? (?:hold|possess)|"
                        r"(?:comptia|security\+|cissp|ccna|itil|dod 8|iat|active (?:secret|ts)|u\.?s\.? citizen))", re.I)
HEADING_DUTY = re.compile(r"^(?:responsibilit|duties|what you(?:'ll)? do|the opportunity|job (?:summary|description)|"
                          r"about (?:the|this) (?:role|job|position)|overview|position summary)", re.I)

# Platforms that are deal-breakers when required and missing from the resume (you can't fake 3 years of Epic)
SPECIALTIES = [
    ("Epic", r"\bepic\b"), ("SAP", r"\bsap\b|s/?4 ?hana"), ("Oracle EBS / Fusion", r"e-?business suite|\bebs\b|oracle fusion|oracle hcm"),
    ("Mainframe / COBOL", r"mainframe|cobol|\bcics\b|z/os|\bjcl\b|rexx|\bidms\b"), ("GIS", r"\bgis\b|arcgis|qgis"),
    ("ServiceNow development", r"servicenow (?:develop|engineer|architect)|glide|flow designer|service portal"),
    ("Salesforce", r"salesforce"), ("Documentum", r"documentum"), ("Genesys", r"genesys"), ("Allscripts / Cerner", r"allscripts|cerner"),
    ("Workday", r"workday (?:hcm|financials|integration)"), ("Power BI development", r"power bi|\bdax\b"),
    ("Palantir", r"palantir|foundry"), ("Databricks", r"databricks"), ("Kubernetes", r"kubernetes|\beks\b|\baks\b|openshift"),
    ("F5", r"\bf5\b|big-?ip"), ("Database administration", r"\bdba\b|database administrat"), ("PKI / certificate authority", r"\bpki\b|certificate authority"),
    ("Splunk administration", r"splunk (?:design|admin|architect|engineer)"), ("Deltek Costpoint", r"costpoint"),
    ("Tactical radios / avionics", r"tactical radio|avionic|aircraft"),
    ("Aerospace / weapons systems engineering", r"\bmbse\b|model-based systems|sysml|flight[- ](?:test|environment)|weapon system|"
     r"missile|spacecraft|satellite|test (?:and|&) evaluation|requirements[- ](?:based )?(?:verification|decomposition)|"
     r"\bhil\b|hardware[- ]in[- ]the[- ]loop|telemetry|embedded(?:/real-time)? software|real-time software|do-178|mil-?std"),
    ("ServiceNow administration", r"servicenow (?:system |platform )?(?:admin|administrator|platform)"), ("Medical / clinical licensure", r"\bbls\b|\bemt\b|nclex|registered nurse"),
]
SPECIALTY_RX = [(n, re.compile(p, re.I)) for n, p in SPECIALTIES]

CLEAR_LEVEL = r"(ts/sci|top secret|\bts\b|secret|public trust)"
CLEAR_ACTIVE = [
    re.compile(r"must currently possess:?\s*\n?\s*(?!none|n/a|not required)" + CLEAR_LEVEL, re.I),
    re.compile(r"(?:minimum )?clearance required to start:?\s*\n?\s*(?!none|public trust)" + CLEAR_LEVEL, re.I),
    re.compile(r"\b(?:active|current|existing)\s+(?:dod\s+|us\s+|u\.s\.\s+)?(?:government\s+)?" + CLEAR_LEVEL, re.I),
    re.compile(CLEAR_LEVEL + r"[^.\n]{0,40}(?:clearance\s+)?(?:is\s+)?required (?:to start|for start|prior to start)", re.I),
    re.compile(r"(?:requires|require) an? " + CLEAR_LEVEL + r"[^.\n]{0,30}(?:to start|clearance)", re.I),
    re.compile(r"\bmust (?:have|hold|possess) (?:an? )?(?:active |current )?" + CLEAR_LEVEL, re.I),
    re.compile(r"clearance required for start:?\s*yes", re.I),
    re.compile(r"(?<!obtain )(?<!obtain an )(?<!obtain a )" + CLEAR_LEVEL + r"\s+(?:security\s+)?clearance\s+(?:is\s+)?required\b", re.I),
    re.compile(r"^\s*(?:active\s+)?" + CLEAR_LEVEL + r"\s+(?:security\s+)?clearance\.?\s*$", re.I | re.M),
]
CLEAR_OBTAIN = re.compile(r"(?:ability|able|eligib\w*)\s+(?:to\s+)?(?:obtain|be granted)[^.\n]{0,40}" + CLEAR_LEVEL +
                          r"|must be able to obtain:?\s*\n?\s*" + CLEAR_LEVEL, re.I)

CERT_NOW = re.compile(r"currently (?:possess|hold|have)|at (?:time of )?(?:start|hire)|prior to start|upon hire|must (?:possess|hold|have)|"
                      r"\bactive\b|\bcurrent\b|required", re.I)
CERT_LATER = re.compile(r"within (?:\d+|six|three|twelve) (?:months|days)|ability to (?:obtain|attain)|willing(?:ness)? to obtain|"
                        r"obtain (?:within|after)|or (?:the )?ability to", re.I)
CERT_RX = {
    "Security+": r"security\s?\+|sec\+|comptia security|\biat (?:level )?(?:ii|2)\b|8570|8140",
    "A+": r"\ba\+|comptia a\b", "Network+": r"network\s?\+", "CCNA": r"\bccna\b", "CCNP": r"\bccnp\b",
    "CISSP": r"\bcissp\b", "CISM": r"\bcism\b", "CISA": r"\bcisa\b(?! \()", "CEH": r"\bceh\b", "OSCP": r"\boscp\b|osep|oswe|\bgxpn\b",
    "GIAC": r"\bgiac\b|\bgsec\b|\bgcih\b|\bgcia\b|\bgpen\b", "CySA+": r"cysa", "CASP+": r"casp|securityx", "ITIL": r"\bitil\b[^.\n]{0,15}(?:foundation|certif)|(?:certif\w*|certified)[^.\n]{0,25}\bitil\b",
    "PMP": r"\bpmp\b", "CBET": r"\bcbet\b", "Cloud certification": r"aws certified|solutions architect associate|gcp cloud engineer|cloud professional",
}
CERT_RX = {k: re.compile(v, re.I) for k, v in CERT_RX.items()}
HARD_CERTS = {"CISSP", "CISM", "CISA", "OSCP", "CCNP", "PMP", "GIAC", "CASP+", "CBET", "Cloud certification"}

TRAVEL = re.compile(r"(\d{2,3})\s?%\s*(?:of the time\s*)?(?:travel|of travel)|travel[^.\n]{0,30}?(\d{2,3})\s?%|"
                    r"(\d{2,3})\s?[-–]\s?(\d{2,3})%\s*(?:of the time|travel)", re.I)
ONSITE_ELSEWHERE = re.compile(r"(?:must|required to)\s+(?:be\s+)?(?:local to|reside (?:in|within)|live within|relocate to)\s+([^.\n]{3,60})|"
                              r"on-?site,? in-?person at (?:the )?([^.\n]{3,40})|candidates must reside within (\d+) miles of ([^.\n]{3,40})", re.I)
# "Bachelor's degree in Electrical/Mechanical/Aerospace Engineering" without IT/CS as an option
ENGINEERING_DEGREE = re.compile(r"degree[^.\n]{0,40}\bin (?:electrical|mechanical|aerospace|chemical|civil|industrial|"
                                r"systems)\s+engineering(?![^.\n]{0,80}(?:information|computer science|cyber|technology))|"
                                r"degree from an accredited course of study in engineering", re.I)
ENROLLED = re.compile(r"currently (?:enrolled|pursuing)|working towards? (?:a |your )?degree|pursuing (?:a |an )?(?:bachelor|degree|associate)|"
                      r"enrolled in (?:a|an|an accredited)", re.I)
EQUIV = re.compile(r"or equivalent|equivalent (?:combination|experience|work)|in lieu of|may be substituted|considered in lieu|"
                   r"additional experience (?:may|will) be (?:considered|substituted)|or \d+ (?:additional )?years", re.I)


def _num(s):
    return int(s) if s.isdigit() else WORDNUM.get(s.lower(), 0)


def split_lines(text):
    text = re.sub(r"&#xa;", "\n", text or "")
    parts = re.split(r"\n+|[•·▪●◦]|(?<=[.;:])\s+(?=[A-Z0-9(])|\s-\s(?=[A-Z])", text)
    return [" ".join(p.split()) for p in parts if len(p.split()) >= 2]


def classify_lines(lines):
    """Tag every line as required / preferred / duty / boilerplate using headings and inline cues."""
    out, mode = [], "duty"
    for line in lines:
        low = line.lower().strip(" :*!")
        if BOILERPLATE.search(line):
            out.append(("boilerplate", line)); continue
        if len(line) < 70 and HEADING_PREF.search(low):
            mode = "preferred"; out.append(("heading", line)); continue
        if len(line) < 70 and HEADING_REQ.search(low):
            mode = "required"; out.append(("heading", line)); continue
        if len(line) < 70 and HEADING_DUTY.search(low):
            mode = "duty"; out.append(("heading", line)); continue
        kind = mode
        if re.search(r"\brequired\b|\bmust\b", line, re.I):  # "2 years required, UNIX preferred" is a requirement
            kind = "required"
        elif PREFERRED.search(line):
            kind = "preferred"
        elif mode != "preferred" and (REQUIRED.search(line) or QUAL_START.search(line)
                                      or re.search(r"\b\d{1,2}\+?\s*(?:years|yrs)\b", line, re.I)):
            kind = "required"
        out.append((kind, line))
    return out


YEARS_RX = re.compile(r"\b" + NUM + r"\s*(?:\+|or more)?\s*(?:\(\d+\)\s*)?(?:years?|yrs)['’]?", re.I)
YEARS_FIRST = re.compile(r"(?:years?|yrs)[^.;\n]{0,20}\bwith (?:an? |a )?(?:bs|ba|ms|ma|hs|as|bachelor|master|associate|high school|phd)", re.I)


def degree_years(lines):
    """{degree_level: years} from combos like 'Bachelor's and 5 years or Associate's and 7 years or HS and 9 years',
    pairing each degree with the nearest years figure on its side (handles both 'BS and 5 years' and '5 years with BS')."""
    found = {}
    for line in lines:
        degs = []
        for key, rx in DEGREE_RX:
            for m in rx.finditer(line):
                if not any(a <= m.start() < b for a, b, _ in degs):
                    degs.append((m.start(), m.end(), key))
        degs.sort()
        years = [(m.start(), m.end(), _num(m.group(1))) for m in YEARS_RX.finditer(line)]
        if not degs or not years:
            continue
        years_first = bool(YEARS_FIRST.search(line))
        for i, (ds, de, key) in enumerate(degs):
            nxt = degs[i + 1][0] if i + 1 < len(degs) else len(line)
            prv = degs[i - 1][1] if i > 0 else 0
            if years_first:
                cand = [y for y in years if prv <= y[1] <= ds]
                pick = cand[-1] if cand else None
            else:
                cand = [y for y in years if de <= y[0] < nxt and y[0] - de < 120]
                pick = cand[0] if cand else None
            if pick and not years_first and re.match(
                    r"[^.;\n]{0,40}(?:may be substituted|can be substituted|in lieu|substitut\w* for|instead of)",
                    line[pick[1]:], re.I):
                continue  # "(4 years of comparable experience may be substituted for a degree)"
            if pick:
                found.setdefault(DEGREES[key], pick[2])
        lieu = re.search(r"\b" + NUM + r"\s*\+?\s*(?:years?|yrs)(?: of (?:relevant |related )?experience)?\s+in lieu of (?:a |any )?degree", line, re.I)
        if lieu and found:
            found.setdefault(DEGREES["hs"], _num(lieu.group(1)))  # "12 years in lieu of a degree" = no-degree path
    return found


def general_years(tagged):
    """Smallest overall experience requirement in required lines (ignores 'N years of <niche platform>')."""
    vals = []
    for kind, line in tagged:
        if kind != "required" or any(rx.search(line) for _, rx in DEGREE_RX):
            continue
        for m in re.finditer(r"\b" + NUM + r"\s*(?:\+|or more)?\s*(?:\(\d+\)\s*)?(?:years?|yrs)['’]?\s*(?:of\s+)?([^.;\n]{0,60})", line, re.I):
            n, rest = _num(m.group(1)), m.group(2).lower()
            if 0 < n <= 25 and not re.search(r"\bold\b|of age|residen|citizen|consecutive", rest):
                vals.append(n)
    return max(vals) if vals else None


def domain_years(tagged, find=None):
    """Requirements like '3+ years of Cyber Incident Response' or '6+ years as a security engineer':
    [(years, [skills named in the line], role_phrase)] so the scorer can check experience in that specific field."""
    out = []
    for kind, line in tagged:
        if kind != "required" or any(rx.search(line) for _, rx in DEGREE_RX):
            continue
        m = YEARS_RX.search(line)
        if not m:
            continue
        n = _num(m.group(1))
        if not 0 < n <= 20:
            continue
        rest = line[m.end():]
        role = re.search(r"\bas an? ([a-z /&-]{3,40}?)(?:\s+in\b|,|\.|$)", rest, re.I)
        out.append((n, (find or skills.find_skills)(rest), role.group(1).strip() if role else None))
    return out


def clearance(text):
    active = None
    for rx in CLEAR_ACTIVE:
        m = rx.search(text)
        if m:
            lvl = (m.group(1) if m.groups() else "secret") or "secret"
            if "public trust" not in lvl.lower():
                active = lvl.upper().replace("TOP SECRET", "TS")
                break
    obtain = CLEAR_OBTAIN.search(text)
    return {"active": active, "obtain": obtain.group(1) if obtain and obtain.group(1) else
            (obtain.group(2) if obtain and obtain.lastindex and obtain.lastindex >= 2 else None)}


def certs(tagged):
    req, pref = {}, set()
    for kind, line in tagged:
        if kind in ("boilerplate", "heading"):
            continue
        for name, rx in CERT_RX.items():
            if not rx.search(line):
                continue
            if kind == "preferred":
                pref.add(name)
            elif kind == "required" or CERT_NOW.search(line):
                timing = "later" if CERT_LATER.search(line) else "now"
                if req.get(name) != "now":
                    req[name] = timing
            else:
                pref.add(name)
    return req, sorted(pref - set(req))


def parse(text, title=""):
    lines = split_lines(text)
    tagged = classify_lines(lines)
    req_text = "\n".join(l for k, l in tagged if k == "required")
    pref_text = "\n".join(l for k, l in tagged if k == "preferred")
    duty_text = "\n".join(l for k, l in tagged if k == "duty")
    deg_lines = [l for k, l in tagged if k in ("required", "duty") and any(rx.search(l) for _, rx in DEGREE_RX)]
    deg_years = degree_years([l for k, l in tagged if k in ("required", "duty")])
    min_degree, strict, flexible_here = None, False, False
    for line in deg_lines:
        if not re.search(r"degree|diploma|graduat|bachelor|associate|master", line, re.I):
            continue
        for key, rx in DEGREE_RX:
            if rx.search(line):
                lvl = DEGREES[key]
                if min_degree is None or lvl < min_degree:
                    min_degree = lvl
                    strict = bool(re.search(r"required|must", line, re.I)) and not EQUIV.search(line)
                    flexible_here = bool(EQUIV.search(line))
    if deg_years:
        min_degree = min(deg_years)
    full = text or ""
    req_certs, pref_certs = certs(tagged)
    specialties = [n for n, rx in SPECIALTY_RX if rx.search(req_text)]
    title_only = [n for n, rx in SPECIALTY_RX if n not in specialties and rx.search(title or "")]
    # "Epic certification ... required within 18 months of hire" = they train you; not a day-one blocker
    trainable = [n for n, rx in SPECIALTY_RX if n in specialties and any(
        rx.search(l) and re.search(r"within [^.\n]{0,25}(?:months|days)|after hire|of hire|training (?:is )?provided|will be trained", l, re.I)
        for k, l in tagged if k == "required")]
    specialties = [n for n in specialties if n not in trainable]
    title_only += trainable
    s_req, s_pref, s_duty = skills.find_skills(req_text), skills.find_skills(pref_text), skills.find_skills(duty_text)
    s_title = skills.find_skills(title or "")
    travel = [int(x) for m in TRAVEL.finditer(full) for x in m.groups() if x]
    onsite = ONSITE_ELSEWHERE.search(full)
    return {
        "skills_required": list(dict.fromkeys(s_req + s_title)),
        "skills_preferred": [s for s in s_pref if s not in s_req],
        "skills_duties": s_duty,
        "skills_all": sorted(set(s_req + s_pref + s_duty + s_title)),
        "years": general_years(tagged),
        "years_by_degree": deg_years,
        "min_degree": min_degree,
        "degree_strict": strict and not flexible_here,
        "degree_flexible": flexible_here,
        "degree_flexible_anywhere": bool(EQUIV.search(full)),
        "domain_years": domain_years(tagged),
        "it_skill_count": len(set(s_req + s_pref + s_duty)),
        "enrolled_ok": bool(ENROLLED.search(full)),
        "clearance": clearance(full),
        "certs_required": req_certs,
        "certs_preferred": pref_certs,
        "specialties": specialties,
        "specialties_title": title_only,
        "engineering_degree": bool(ENGINEERING_DEGREE.search(req_text)),
        "travel": max(travel) if travel else None,
        "onsite_text": next((g for g in onsite.groups() if g), None) if onsite else None,
        "required_lines": [l for k, l in tagged if k == "required"][:25],
    }
