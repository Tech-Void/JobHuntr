"""Read resume text out of uploaded files and turn it into the structured profile used for job matching."""
import html
import io
import re
import unicodedata
import zipfile
from datetime import date

from . import skills
from .requirements import CERT_RX, DEGREE_RX, DEGREES

# Lines describing practice rather than paid work: skills found only here count as "lab level"
LAB_LINE = re.compile(r"\blab\b|home ?lab|coursework|course work|introductory|exposure|familiar|tryhackme|hack ?the ?box|"
                      r"\bctf\b|capstone|class project|academic|learning|self-taught|mock|practice|simulat", re.I)
IN_PROGRESS = re.compile(r"in progress|in-progress|pursuing|studying|planned|expected|anticipated|scheduled|working toward|"
                         r"currently enrolled|candidate\b|\(\d{4}\)\s*$", re.I)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_RANGE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})\s*[-–—to]+\s*"
                        r"(present|current|now|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4})", re.I)
IT_ROLE = re.compile(r"\bit\b|information technology|tech|support|admin|system|network|cyber|security|help ?desk|desktop|"
                     r"computer|engineer|analyst|developer|infrastructure", re.I)


def clean_text(text: str) -> str:
    """Undo HTML entities and odd encodings that come out of Word/PDF exports."""
    text = html.unescape(html.unescape(text or ""))
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("�", " · ").replace("•", "·")
    return re.sub(r"[ \t]+", " ", text)


def text_from_file(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader  # imported lazily so the app starts fast
        reader = PdfReader(io.BytesIO(data))
        return clean_text("\n".join(page.extract_text() or "" for page in reader.pages))
    if name.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"<w:tab/>", "\t", xml)
        xml = re.sub(r"</w:p>", "\n", xml)
        return clean_text(re.sub(r"<[^>]+>", "", xml))
    if name.endswith((".txt", ".md")):
        return clean_text(data.decode("utf-8", "ignore"))
    raise ValueError("Use a .pdf, .docx or .txt file (or paste the text)")


def _years(text):
    """Years of IT experience: an explicit '6+ years' claim, else the span of IT job date ranges."""
    m = re.search(r"\b(\d{1,2})\+?\s*(?:years|yrs)\b[^.\n]{0,60}(?:experience|hands-on|professional|in it|it )", text, re.I)
    if m:
        return int(m.group(1))
    spans = []
    for line in text.splitlines():
        for d in DATE_RANGE.finditer(line):
            if not IT_ROLE.search(line):
                continue
            start = date(int(d.group(2)), MONTHS[d.group(1)[:3].lower()], 1)
            end_s = d.group(3).lower()
            if end_s[:3] in MONTHS:
                parts = end_s.split()
                end = date(int(parts[-1]), MONTHS[end_s[:3]], 1)
            else:
                end = date.today()
            spans.append((start, end))
    if not spans:
        return None
    start, end = min(s for s, _ in spans), max(e for _, e in spans)
    return max(0, round((end - start).days / 365.25))


def _degrees(text):
    """(highest completed level, highest in-progress level) from the education lines."""
    done, prog = 0, 0
    for line in text.splitlines():
        if not re.search(r"degree|bachelor|associate|master|diploma|b\.?a\.?t|a\.?a\.?s|b\.?s\.?|b\.?a\.?|m\.?s\.?|phd|ged", line, re.I):
            continue
        level = 0
        if re.search(r"bachelor|b\.?a\.?t\.?\b|\bb\.?s\.?\b|\bb\.?a\.?\b", line, re.I):
            level = 3
        for key, rx in DEGREE_RX:
            if rx.search(line):
                level = max(level, DEGREES[key])
                break
        if re.search(r"\ba\.?a\.?s\.?\b|associate", line, re.I):
            level = max(level, 2) if level in (0, 2) else level
        if not level:
            continue
        if IN_PROGRESS.search(line) or re.search(r"expected|20(2[6-9]|3\d)\s*$", line, re.I) and "expected" in line.lower():
            prog = max(prog, level)
        else:
            done = max(done, level)
    return done or 1, prog  # assume a high school diploma if nothing else is listed


def _certs(text):
    held, progress = set(), set()
    for line in text.splitlines():
        for name, rx in CERT_RX.items():
            if name == "Security+" and re.search(r"8570|8140|iat", line, re.I) and not re.search(r"security\s?\+", line, re.I):
                continue
            for m in rx.finditer(line):
                tail = line[m.end():m.end() + 30]
                (progress if IN_PROGRESS.search(tail) or IN_PROGRESS.search(line[max(0, m.start() - 15):m.start()]) else held).add(name)
    return sorted(held), sorted(progress - held)


def _clearance(text):
    m = re.search(r"\b(active|current|interim)?\s*(ts/sci|top secret|secret|public trust)\b(?: clearance)?", text, re.I)
    if not m or not re.search(r"clearance|active|current|interim", m.group(0) + text[m.end():m.end() + 12], re.I):
        return "none"
    return m.group(2).lower().replace("top secret", "ts")


PROFILE_VERSION = 2  # bump when profile parsing changes so saved profiles are rebuilt
SECTION = re.compile(r"^[A-Z][A-Z &/,]{5,}$")
LAB_SECTION = re.compile(r"project|lab|training|coursework", re.I)


def split_work_and_lab(text):
    """Split resume text into work-experience snippets and lab/coursework snippets.
    Whole sections like 'TECHNICAL PROJECTS & LAB WORK' are lab; elsewhere each comma/semicolon item is judged
    on its own, so 'Python, Bash, Autopsy (lab), AWS (introductory)' only marks Autopsy and AWS as lab-level."""
    work, lab, in_lab = [], [], False
    for line in text.splitlines():
        stripped = line.strip()
        if SECTION.match(stripped):
            in_lab = bool(LAB_SECTION.search(stripped)) and not re.search(r"experience|skills", stripped, re.I)
            continue
        if in_lab or re.search(r"tryhackme|hack ?the ?box|home ?lab", stripped, re.I):
            lab.append(stripped)
            continue
        for seg in re.split(r"[,;]|\bincluding\b", stripped):
            (lab if LAB_LINE.search(seg) else work).append(seg)
    return work, lab


def build_profile(resume_text: str, extra: str, overrides: dict | None = None) -> dict:
    """extra = comma-separated skills/certs the resume doesn't mention (e.g. 'Security+ (in progress), Splunk').
    overrides = values the user corrected on the My resume page (years, degree, clearance...)."""
    text = clean_text(resume_text or "")
    extra_list = [x.strip() for x in (extra or "").split(",") if x.strip()]
    work_lines, lab_lines = split_work_and_lab(text)
    work_skills = set(skills.find_skills("\n".join(work_lines)) + skills.find_skills(", ".join(extra_list)))
    lab_only = set(skills.find_skills("\n".join(lab_lines))) - work_skills
    done, prog = _degrees(text)
    held, progress = _certs(text + "\n" + "\n".join(extra_list))
    detected = {"years": _years(text), "degree": done, "degree_in_progress": prog if prog > done else 0,
                "certs": held, "certs_in_progress": progress, "clearance": _clearance(text)}
    o = {k: v for k, v in (overrides or {}).items() if v not in (None, "")}
    return {
        "v": PROFILE_VERSION,
        "resume_text": text,
        "extra": extra or "",
        "skills": sorted(work_skills | lab_only),
        "skills_lab": sorted(lab_only),
        "detected": detected,
        "overrides": o,
        "facts": {**detected, **o},
        "headline": next((l.strip() for l in text.splitlines()[1:4] if re.search(r"support|admin|security|cyber|network|engineer|analyst", l, re.I)), ""),
        "words": len(text.split()),
    }
