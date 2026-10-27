"""How well a job fits the user: one 0-100 score plus the reasons behind it.

The score starts from role relevance and skill coverage, then hard requirements the user doesn't meet
(experience for their degree, an active clearance, certs needed on day one, niche platforms, seniority)
multiply it down. Every adjustment is recorded as a reason so the UI can explain the number.
"""
import json
import re

from . import requirements
from .matching import classify_it

CORE_TRACKS = {"IT Support", "Sysadmin / Infrastructure", "Cybersecurity", "Forensics / DFIR"}
LEVEL_NAMES = {1: "high school", 2: "an associate's", 3: "a bachelor's", 4: "a master's", 5: "a PhD"}
CLEAR_RANK = {"none": 0, "public trust": 1, "secret": 2, "ts": 3, "ts/sci": 4}

LEADERSHIP = re.compile(r"\b(?:lead|principal|manager|director|architect|chief|head of|vp|vice president|sme|"
                        r"subject matter expert|expert|supervisor|staff (?:engineer|analyst))\b", re.I)
SENIOR = re.compile(r"\b(?:senior|sr\.?|iii|staff)\b", re.I)
LEVEL4 = re.compile(r"\b(?:iv|v|level ?[45])\b", re.I)
ENTRY = re.compile(r"\b(?:junior|jr\.?|entry|associate|i|ii|level ?[12]|tier ?[12]|technician|intern|apprentice|trainee)\b", re.I)
INTERN = re.compile(r"\bintern(?:ship)?\b|co-?op\b", re.I)
PM_ROLE = re.compile(r"product owner|product manager|program manager|project manager|scrum master|business analyst|"
                     r"business (?:systems|applications) analyst|change (?:coordinator|manager)|consultant|instructional|trainer", re.I)
# soft skills count little toward a match: everybody "has" them
GENERIC = {"Microsoft Office", "Documentation / SOPs", "Customer service", "Project coordination", "Training users",
           "Vendor management"}
# umbrella skills that ride along with specific ones ("Kernel-based Virtual Machines" also says "virtual machines")
BROAD = {"Virtualization", "Linux", "Windows 10/11", "Help desk / ticketing", "TCP/IP", "Hardware troubleshooting",
         "Customer service", "Routing & switching"}
# partial credit when the resume shows the underlying skill but not the exact tool
EQUIVALENT = {
    "ServiceNow": [("Help desk / ticketing", 0.6)], "Remedy / Jira": [("Help desk / ticketing", 0.6)],
    "ITIL": [("Help desk / ticketing", 0.4)], "VMware": [("Virtualization", 0.6)], "Hyper-V": [("Virtualization", 0.6)],
    "Citrix / VDI": [("Virtualization", 0.4)], "KVM / Linux virtualization": [("Virtualization", 0.4), ("Linux", 0.2)],
    "Server hardware / lights-out": [("Hardware troubleshooting", 0.4)], "Group Policy": [("Active Directory", 0.5)],
    "Entra ID / Azure AD": [("Active Directory", 0.5)], "Intune": [("Mobile devices / MDM", 0.5), ("Patch management", 0.3)],
    "SCCM / MECM": [("Patch management", 0.5), ("Imaging / deployment", 0.4)], "Cisco": [("Routing & switching", 0.6)],
    "Firewalls": [("Routing & switching", 0.3), ("Endpoint security", 0.3)], "Splunk": [("SIEM", 0.5)],
    "Microsoft Sentinel": [("SIEM", 0.5)], "SIEM": [("SOC operations", 0.4)], "EDR / XDR": [("Endpoint security", 0.5)],
    "Vulnerability management": [("Patch management", 0.4), ("Nmap / scanning", 0.3)], "PowerShell": [("Python", 0.3), ("Bash / shell scripting", 0.3)],
    "Microsoft 365": [("Exchange", 0.6), ("Microsoft Office", 0.3)], "Exchange": [("Microsoft 365", 0.6)],
    "NOC / monitoring": [("Network monitoring", 0.6)], "Wireless": [("Routing & switching", 0.4)],
    "Windows 10/11": [("Hardware troubleshooting", 0.3)], "STIGs / hardening": [("Patch management", 0.3), ("NIST / RMF", 0.3)],
}


def _cand(profile):
    f = (profile or {}).get("facts") or {}
    return {
        "years": f.get("years") if f.get("years") is not None else 0,
        "degree": f.get("degree") or 1,
        "degree_in_progress": f.get("degree_in_progress") or 0,
        "certs": set(f.get("certs") or []),
        "certs_in_progress": set(f.get("certs_in_progress") or []),
        "clearance": (f.get("clearance") or "none").lower(),
        "skills": set((profile or {}).get("skills") or []),
        "lab": set((profile or {}).get("skills_lab") or []),
    }


def credit(skill, cand):
    """1.0 = done it at work, 0.5 = lab/coursework only, partial for a related skill, else 0."""
    if skill in cand["skills"]:
        return 0.5 if skill in cand["lab"] else 1.0
    best = 0.0
    for other, w in EQUIVALENT.get(skill, []):
        if other in cand["skills"]:
            best = max(best, w * (0.5 if other in cand["lab"] else 1.0))
    return best


def related_to(skill, cand):
    """Name of the resume skill that gives partial credit for this one, if any."""
    for other, _ in EQUIVALENT.get(skill, []):
        if other in cand["skills"]:
            return other
    return None


def _coverage(wanted, cand):
    """Weighted share of wanted skills the candidate has (soft skills weigh 0.3)."""
    if not wanted:
        return None
    weights = [0.3 if s in GENERIC else 1.0 for s in wanted]
    if sum(weights) < 0.9:  # only soft skills listed: don't let them carry a match
        return None
    return sum(w * credit(s, cand) for s, w in zip(wanted, weights)) / sum(weights)


def score(title, req, profile, track=None):
    """req = requirements.parse(...) output. Returns {'fit', 'label', 'reasons', 'skills', 'blockers', 'skill_fit'}."""
    c = _cand(profile)
    reasons, blockers = [], []
    track = track or (classify_it(title) or (None,))[0]

    # --- 1. how relevant is this kind of role ---------------------------------------------------------
    if PM_ROLE.search(title or ""):
        relevance = 0.4
        reasons.append(("-", "Project, product or business-analysis role"))
    elif track in CORE_TRACKS:
        relevance = 1.0
    elif track == "Adjacent IT":
        relevance = 0.4
        reasons.append(("-", "Adjacent to your field (development, data or business systems)"))
    elif track:
        relevance = 0.7
    else:
        it_skills = len(req["skills_required"]) + len(req["skills_duties"])
        relevance = 0.5 if it_skills >= 5 else 0.15
        if relevance < 0.5:
            reasons.append(("-", "Not an IT role"))
    if track and req.get("it_skill_count", 1) == 0:
        relevance *= 0.5
        reasons.append(("-", "Description doesn't mention any IT skills"))

    # --- 2. skill coverage: required counts double ---------------------------------------------------
    req_s, pref_s = req["skills_required"], req["skills_preferred"] + req["skills_duties"]
    cov_req, cov_pref = _coverage(req_s, c), _coverage(list(dict.fromkeys(pref_s)), c)
    if cov_req is None and cov_pref is None:
        skill = 0.55  # posting lists no recognisable skills: neutral
    elif cov_req is None:
        skill = cov_pref
    elif cov_pref is None:
        skill = cov_req
    else:
        skill = 0.7 * cov_req + 0.3 * cov_pref
    # little evidence -> pull toward neutral (2 of 2 recognised skills shouldn't read as a perfect match)
    n_seen = len(set(req_s) | set(pref_s))
    if n_seen < 6:
        skill = (n_seen * skill + (6 - n_seen) * 0.55) / 6
    exact = [s for s in req_s if s in c["skills"]]
    related = [s for s in req_s if s not in c["skills"] and credit(s, c) >= 0.3]
    if req_s:
        good = len(exact) + 0.5 * len(related) >= len(req_s) / 2
        reasons.append(("+" if good else "-", f"You have {len(exact)} of {len(req_s)} required skills"
                        + (f" (+{len(related)} related)" if related else "")))
    base = relevance * (0.4 + 0.6 * skill)

    # --- 3. hard requirements multiply the score down ------------------------------------------------
    mult = 1.0
    title_l = title or ""

    def gate(factor, text, blocker=False):
        nonlocal mult
        mult *= factor
        reasons.append(("-", text))
        if blocker:
            blockers.append(text)

    # experience needed *for this candidate's degree*
    need = None
    byd = {int(k): v for k, v in (req.get("years_by_degree") or {}).items()}
    if byd:
        usable = [v for lvl, v in byd.items() if lvl <= c["degree"]]
        need = min(usable) if usable else None
        if need is None and req.get("degree_flexible_anywhere"):
            # "Bachelor's + 2 years ... additional experience may be considered in lieu of degree"
            need = min(byd.values()) + 2 * (min(byd) - c["degree"])
            reasons.append(("+", "Experience can substitute for the degree"))
        elif need is None:  # every path needs more education than they have
            lowest = min(byd)
            gate(0.55, f"Needs {LEVEL_NAMES.get(lowest, 'a degree')} degree or higher")
    elif req.get("years") is not None:
        need = req["years"]
    if need is not None:
        gap = need - c["years"]
        if gap <= 0:
            reasons.append(("+", f"Experience: needs {need}+ yrs, you have {c['years']}"))
        else:
            factor = {1: 0.85, 2: 0.7, 3: 0.5, 4: 0.35}.get(gap, 0.2)
            gate(factor, f"Needs {need}+ yrs experience (you have {c['years']})", blocker=gap >= 3)

    # experience in a specific field ("3+ years of incident response", "6+ years as a security engineer")
    worst = None
    for n, field_skills, role in req.get("domain_years") or []:
        core = [s for s in field_skills if s not in GENERIC]
        specific = [s for s in core if s not in BROAD]
        core = specific or core  # "5 yrs of KVM (virtual machines)" is about KVM, not virtualization in general
        if role and not re.search(r"\b(?:it|support|technician|administrator|admin|help ?desk|specialist|manager)\b", role, re.I):
            have = 0
        elif core:
            have = max(credit(s, c) for s in core)
        else:
            continue
        domain_gap = n - (c["years"] if have >= 1.0 else 0)  # lab/coursework isn't professional experience
        if domain_gap >= 2 and (worst is None or domain_gap > worst[0]):
            worst = (domain_gap, n, role or ", ".join(core[:2]))
    if worst and not (need is not None and need - c["years"] >= worst[0]):
        gap, n, what = worst
        gate({2: 0.75, 3: 0.6, 4: 0.5}.get(int(gap), 0.4), f"Wants {n}+ yrs specifically in {what}")

    # degree
    md = req.get("min_degree")
    if md and md > c["degree"] and not byd and not req.get("degree_flexible"):
        if req.get("enrolled_ok") and c["degree_in_progress"] >= md:
            reasons.append(("+", "Accepts students: you're enrolled"))
        elif req.get("degree_strict"):
            gate(0.55 if c["degree_in_progress"] >= md else 0.45, f"Requires {LEVEL_NAMES.get(md, 'a')} degree")
        else:
            gate(0.9, f"Prefers {LEVEL_NAMES.get(md, 'a')} degree (experience may substitute)")
    elif req.get("enrolled_ok") and c["degree_in_progress"]:
        reasons.append(("+", "Open to current students"))

    # clearance
    active = (req.get("clearance") or {}).get("active")
    if active:
        if CLEAR_RANK.get(c["clearance"], 0) >= CLEAR_RANK.get(active.lower(), 2):
            reasons.append(("+", f"You hold the required {active} clearance"))
        else:
            gate(0.15, f"Needs an active {active} clearance to start", blocker=True)
    elif (req.get("clearance") or {}).get("obtain"):
        reasons.append(("+", f"Will sponsor a {req['clearance']['obtain']} clearance"))

    # certifications
    for cert, when in (req.get("certs_required") or {}).items():
        if cert in c["certs"]:
            reasons.append(("+", f"You hold {cert}"))
        elif cert in requirements.HARD_CERTS:
            gate(0.35 if when == "now" else 0.6, f"Requires {cert}" + ("" if when == "now" else " (within months of hire)"),
                 blocker=when == "now")
        elif when == "now":
            gate(0.6 if cert in c["certs_in_progress"] else 0.5,
                 f"Needs {cert} at start" + (" (you're working on it)" if cert in c["certs_in_progress"] else ""))
        else:
            gate(0.92, f"{cert} within months of hire" + (" (in progress)" if cert in c["certs_in_progress"] else ""))

    # niche platforms the resume doesn't show
    missing_spec = [s for s in req.get("specialties") or []
                    if not any(s.split()[0].lower() in k.lower() for k in c["skills"])]
    if missing_spec:
        gate(0.3 if len(missing_spec) == 1 else 0.22, f"Needs {', '.join(missing_spec[:2])} experience", blocker=True)
    title_spec = [s for s in req.get("specialties_title") or [] if s not in missing_spec
                  and not any(s.split()[0].lower() in k.lower() for k in c["skills"])]
    if title_spec:
        gate(0.65, f"Built around {title_spec[0]} (they typically train you after hire)")
    if req.get("engineering_degree"):
        gate(0.5, "Wants an engineering degree (electrical / mechanical / aerospace)")

    # seniority from the title
    if LEADERSHIP.search(title_l):
        light = need is not None and need <= max(2, c["years"] - 2)  # e.g. a "Lead" operator role needing 2 yrs
        gate(0.75 if light else 0.35 if c["years"] < 8 else 0.7,
             "Lead title, but the experience bar is within reach" if light else "Leadership / principal-level role")
    elif LEVEL4.search(title_l):
        gate(0.45, "Level IV/V (very senior) role")
    elif SENIOR.search(title_l):
        gate(0.85 if need is not None and need <= c["years"] else 0.6, "Senior-level title")
    elif INTERN.search(title_l):
        reasons.append(("+", "Internship (often a path to a sponsored clearance)"))
        if c["years"] >= 4:
            mult *= 0.9
    elif ENTRY.search(title_l):
        reasons.append(("+", "Entry / mid-level title"))

    # where & how
    if req.get("travel") and req["travel"] >= 75:
        gate(0.85, f"Up to {req['travel']}% travel")

    fit = round(100 * base * mult)
    skill_fit = round(100 * relevance * (0.4 + 0.6 * skill))
    label = "Strong fit" if fit >= 62 else "Good fit" if fit >= 45 else "Stretch" if fit >= 28 else "Poor fit"
    return {
        "fit": fit, "label": label, "skill_fit": skill_fit, "blockers": blockers,
        "reasons": reasons[:10],
        "skills": {
            "required": [_chip(s, c) for s in req_s],
            "preferred": [_chip(s, c) for s in dict.fromkeys(req["skills_preferred"])],
        },
    }


def _chip(s, c):
    out = {"name": s, "have": s in c["skills"], "lab": s in c["lab"]}
    if not out["have"]:
        rel = related_to(s, c)
        if rel and credit(s, c) >= 0.3:
            out["related"] = rel
    return out


def score_job(job, profile):
    """Score a stored job row (uses its saved requirements, or parses the description on the fly)."""
    facts = job.get("facts")
    facts = json.loads(facts) if isinstance(facts, str) else facts or {}
    req = facts.get("req")
    if not req:
        req = requirements.parse(job.get("description") or "", job.get("title", ""))
    return score(job.get("title", ""), req, profile)
