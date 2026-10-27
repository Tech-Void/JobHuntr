"""Rule-based tailoring: which resume lines to lead with, a skills line in the posting's order, wording to mirror,
and honest advice for each gap. Works offline; the optional AI helper builds on the same idea."""
import re

from . import resume, skills
from .requirements import HARD_CERTS

STOP = set("a an and are as at be by for from has have in into is it its of on or our that the their this to was we will with "
           "you your experience ability strong work working team support including using use etc".split())
BULLET_SKIP = re.compile(r"^(?:professional summary|core skills|education|certifications?|technical projects|[A-Z &/]{6,})$|"
                         r"@|linkedin|\|\s*\w+,\s*[A-Z]{2}\s|\b\d{3}[-.)]\s?\d{3}[-.]\d{4}\b", re.I)
LEVEL_NAMES = {2: "associate's", 3: "bachelor's", 4: "master's"}
VENDOR = re.compile(r"rubrik|veeam|commvault|crowdstrike|sentinelone|carbon black|tenable|qualys|nessus|rapid7|proofpoint|"
                    r"mimecast|okta|\bduo\b|cyberark|beyondtrust|meraki|aruba|palo alto|fortinet|fortigate|solarwinds|nagios|"
                    r"prtg|zabbix|splunk|qradar|elastic|jamf|citrix|cisco|f5|big-?ip|servicenow|remedy|jira", re.I)


def _words(text):
    return {w for w in re.findall(r"[a-z][a-z+#/.-]{2,}", (text or "").lower()) if w not in STOP}


def _bullets(resume_text):
    lines = [l.strip(" ·-•\t") for l in resume.clean_text(resume_text).splitlines()]
    return [l for l in lines if len(l.split()) >= 7 and not BULLET_SKIP.search(l)]


def _span(skill_name, text):
    for name, _, rx in skills.SKILLS:
        if name == skill_name:
            m = rx.search(text or "")
            return m.group(0) if m else None
    return None


def suggest(profile, title, description, req, fit_result):
    rtext = (profile or {}).get("resume_text", "")
    if not rtext.strip():
        return None
    facts = (profile or {}).get("facts") or {}
    mine, lab = set(profile.get("skills") or []), set(profile.get("skills_lab") or [])
    req_skills, pref_skills = req.get("skills_required") or [], (req.get("skills_preferred") or []) + (req.get("skills_duties") or [])
    weight = {s: 2.0 for s in req_skills}
    for s in pref_skills:
        weight.setdefault(s, 1.0)
    job_words = _words("\n".join(req.get("required_lines") or []) + " " + title)

    # 1. resume lines to lead with: most required skills, then shared wording
    ranked = []
    for b in _bullets(rtext):
        hit = [s for s in skills.find_skills(b) if s in weight]
        score = sum(weight[s] for s in hit) + 0.15 * len(_words(b) & job_words)
        if hit or score >= 0.6:
            ranked.append((score, b, hit))
    ranked.sort(key=lambda x: -x[0])
    lead = [{"text": b, "skills": hit} for _, b, hit in ranked[:3]]

    # 2. skills line in the posting's priority order (only skills you actually have)
    ordered = [s for s in dict.fromkeys(req_skills + pref_skills) if s in mine]
    skills_line = ", ".join(f"{s} (lab)" if s in lab else s for s in ordered[:12])

    # 3. say it their way: same skill, different words
    mirror = []
    for s in ordered:
        theirs, yours = _span(s, description), _span(s, rtext)
        if not (theirs and yours) or theirs.lower() == yours.lower() or VENDOR.search(theirs):
            continue  # same words, or they named a product (that's a tool to learn, not wording to copy)
        if len(theirs.split()) == 1 and theirs.islower():
            continue  # a lone generic word like "routing" isn't a phrasing tip
        mirror.append({"skill": s, "theirs": theirs, "yours": yours})
    mirror = mirror[:5]

    # 4. gaps, with something concrete to do about each
    gaps = []
    for cert, when in (req.get("certs_required") or {}).items():
        if cert in set(facts.get("certs") or []):
            continue
        if cert in set(facts.get("certs_in_progress") or []):
            gaps.append(f"{cert} is {'required at start' if when == 'now' else 'expected soon after hire'}. List it as "
                        f"\"CompTIA {cert.rstrip('+')}+ (in progress, exam scheduled <month year>)\" so it isn't screened out.")
        elif cert in HARD_CERTS:
            gaps.append(f"Requires {cert}, which needs years of experience to earn. Treat this role as a longer-term target.")
        else:
            gaps.append(f"Asks for {cert}. If you can, schedule the exam before applying and say so.")
    active = (req.get("clearance") or {}).get("active")
    if active and (facts.get("clearance") or "none") == "none":
        gaps.append(f"Needs an active {active} clearance to start. You can't get one on your own, so favor roles that "
                    f"say \"ability to obtain\" (they sponsor it).")
    md = req.get("min_degree")
    if md and md > (facts.get("degree") or 1) and facts.get("degree_in_progress"):
        gaps.append(f"Asks for a {LEVEL_NAMES.get(md, 'higher')} degree. Put your in-progress degree and expected date near the top "
                    f"(e.g. \"B.A.T. Cybersecurity, expected May 2027\").")
    for kind, text in fit_result.get("reasons", []):
        if kind == "-" and text.startswith(("Needs ", "Wants ")) and "yrs" in text:
            gaps.append(f"{text}. Lead with your total years as the primary IT resource and quantify scope "
                        f"(users supported, devices, uptime) to close the gap.")
            break
    lab_gaps = [s for s in req_skills if s in lab]
    if lab_gaps:
        gaps.append(f"You've only used {', '.join(lab_gaps[:3])} in labs or coursework. Name the lab work explicitly "
                    f"(\"home lab\", \"TryHackMe SOC rooms\") so it still counts.")
    missing = [s for s in req_skills if s not in mine and s not in ("Microsoft Office",)]
    if missing:
        gaps.append(f"Not on your resume: {', '.join(missing[:5])}. Add them only if you've really used them; "
                    f"otherwise expect interview questions here.")
    return {"lead": lead, "skills_line": skills_line, "mirror": mirror, "gaps": gaps[:6]}
