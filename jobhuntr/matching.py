"""Decide which jobs match a saved search, and label them (track, seniority, clearance)."""
import re


def rx(*parts):
    return re.compile("|".join(f"(?:{p})" for p in parts), re.I)


# Titles that look technical but never are (clinical, trades, finance, etc.)
EXCLUDE = rx(r"\bnurs", r"\brn\b", r"physician", r"therap", r"(?<!information )(?<!systems )(?<!cyber )security officer",
             r"security guard", r"\bpolice", r"pharmac", r"surg", r"phlebot", r"medical assistant", r"custod",
             r"\bcook\b", r"\bdriver", r"\bteacher", r"patient", r"dietar", r"housekeep", r"environmental serv",
             r"steril", r"radiolog", r"sonograph", r"ultrasound", r"respiratory", r"laborator", r"\blvn\b", r"\bcna\b",
             r"paramedic", r"\bemt\b", r"dental", r"chaplain", r"social work", r"pilot", r"mechanic", r"electrician",
             r"plumb", r"hvac", r"painter", r"animal", r"financial analyst", r"accountant", r"auditor", r"underwrit",
             r"claims", r"actuar", r"recruiter", r"attorney", r"paralegal", r"food", r"barista", r"cashier", r"sales",
             r"telecommunicator", r"non-it", r"\bhr\b", r"human resources", r"finance", r"procurement",
             r"category manager", r"customer service", r"embedded", r"radar", r"combat", r"\bmbse\b", r"model-based",
             r"flight", r"mission engineering", r"product manager", r"trainer", r"\bstring engineer",
             r"provider network|network (?:development|relations|contract|management (?:coordinator|consultant))",
             r"technologist", r"medical (?:coder|imaging)", r"health information tech")

# (track, base score, pattern) - first match wins
TRACKS = [
    ("Forensics / DFIR", 78, rx(r"forensic", r"\bdfir\b", r"e-?discovery", r"digital evidence", r"malware",
                                r"reverse engineer", r"incident respon", r"threat hunt", r"cyber investigat",
                                r"computer crime", r"digital investigat")),
    ("Cybersecurity", 90, rx(r"cyber", r"information security", r"infosec", r"security analyst", r"security engineer",
                             r"\bsoc\b", r"security operations", r"vulnerab", r"penetration", r"pen ?test", r"red team",
                             r"blue team", r"\bisso\b", r"\bissm\b", r"information assurance", r"\bia\b", r"\brmf\b",
                             r"\bgrc\b", r"identity", r"\biam\b", r"access management", r"\bsiem\b", r"splunk",
                             r"security admin", r"security specialist", r"it security", r"network security",
                             r"cloud security", r"privacy", r"compliance analyst", r"threat", r"\bcissp\b",
                             r"network defense", r"computer network defense", r"\bcnd\b", r"offensive security",
                             r"digital security", r"security (?:engineer|analyst|architect)")),
    ("Sysadmin / Infrastructure", 86, rx(r"system(?:s)? admin", r"sysadmin", r"network admin", r"network engineer",
                                         r"network tech", r"network analyst", r"network specialist",
                                         r"(?:it|technology|cloud|network|systems?) infrastructure",
                                         r"infrastructure (?:engineer|support|analyst|admin|services|tech|specialist|operations)",
                                         r"server", r"windows", r"linux", r"active directory", r"vmware", r"cloud",
                                         r"devops", r"site reliability", r"database admin", r"\bdba\b", r"storage",
                                         r"endpoint", r"intune", r"sccm|mecm", r"azure", r"\baws\b", r"m365|office 365",
                                         r"systems engineer", r"\bnoc\b", r"network operations", r"data center",
                                         r"telecom", r"voip", r"unified comm", r"wireless",
                                         r"\bnetwork(?:ing)?\b", r"computer operations?", r"software install",
                                         r"site reliability", r"system(?:s)? (?:engineer|operations)")),
    ("IT Support", 82, rx(r"help ?desk", r"service desk", r"desktop", r"it support", r"technical support", r"tech support",
                          r"support tech", r"support specialist", r"it tech", r"computer tech", r"deskside", r"end user",
                          r"\bit specialist", r"\bit\b", r"information technology", r"information systems?",
                          r"technology support", r"pc tech", r"field services? (?:tech|engineer|rep)", r"it associate", r"it analyst",
                          r"technical support rep", r"mobile device", r"workstation", r"technology (?:specialist|technician|support)",
                          r"operations support analyst", r"desktop engineer")),
    ("Adjacent IT", 55, rx(r"application analyst", r"applications analyst", r"\bepic\b", r"clinical (?:app|informatics)",
                           r"informatics", r"systems analyst", r"business systems", r"technology", r"software",
                           r"developer", r"data analyst", r"programmer", r"biomed(?:ical)? equip", r"\bhtm\b",
                           r"servicenow")),
]

SENIOR = rx(r"\bsenior\b", r"\bsr\.?(?=\s|$)", r"principal", r"\bstaff\b", r"\blead\b", r"director", r"manager",
            r"\bchief\b", r"head of", r"\bvp\b", r"vice president", r"architect", r"\biii\b", r"\biv\b", r"\bv\b",
            r"supervisor", r"expert", r"\blevel ?[345]\b", r"\b[345]\b")
ENTRY = rx(r"junior", r"\bjr\.?(?=\s|$)", r"entry", r"associate", r"\bintern\b", r"internship", r"apprentic",
           r"trainee", r"\bi\b", r"\blevel ?1\b", r"\btier ?(?:1|i)\b", r"\b1\b", r"technician", r"coordinator",
           r"assistant", r"new grad", r"early career", r"\bii\b", r"\b2\b")
CLEARANCE = rx(r"ts/sci", r"top secret", r"\bsecret\b", r"clearance", r"\bpoly\b", r"\bts\b", r"\bsci\b")


def level_tags(title: str):
    """Return (score adjustment, tags) based on seniority/clearance words in a title."""
    tags, adj = [], 0
    if SENIOR.search(title):
        adj, tags = -25, ["Senior"]
    elif ENTRY.search(title):
        adj, tags = 8, ["Entry/Mid"]
    if CLEARANCE.search(title):
        tags.append("Clearance")
    return adj, tags


DEV_TITLE = rx(r"software (?:engineer|developer|development)", r"developer", r"programmer", r"full[- ]stack",
              r"front[- ]end", r"back[- ]end", r"data (?:engineer|scientist)", r"machine learning|ml|ai engineer")


def classify_it(title: str):
    """Built-in IT/cyber profile. Returns (track, score) or None."""
    if EXCLUDE.search(title):
        return None
    if DEV_TITLE.search(title) and not re.search(r"cyber|security|forensic|site reliability", title, re.I):
        return "Adjacent IT", 55  # "Software Engineer II - Storage" is development, not storage administration
    for track, score, pat in TRACKS:
        if pat.search(title):
            return track, score
    return None


def _keyword_regex(words):
    words = [w.strip() for w in words or [] if w and w.strip()]
    if not words:
        return None
    return re.compile("|".join(r"(?<!\w)" + re.escape(w) + r"(?!\w)" for w in words), re.I)


REQ_ID = re.compile(r"\b[a-z]{0,2}\d{5,}\b|\(.*?\)")


def similarity_key(job):
    """Postings that differ only by requisition number count as the same job (contractors often post 4x)."""
    title = re.sub(r"[^a-z0-9+#]+", " ", REQ_ID.sub(" ", job["title"].lower())).strip()
    place = re.split(r"[(|]", job.get("location", "").lower())[0].strip()
    return job["company"].lower(), title, place


def group_similar(jobs):
    """Collapse duplicate postings into one entry carrying a `similar` list of the others."""
    groups = {}
    for j in jobs:
        groups.setdefault(similarity_key(j), []).append(j)
    out = []
    for members in groups.values():
        # keep the one the user has touched; else the one with details; else the oldest
        members.sort(key=lambda j: (j.get("status") is None, not j.get("starred"), j.get("facts") is None,
                                    j.get("first_seen", "")))
        lead = dict(members[0])
        lead["similar"] = [{"id": m["id"], "url": m["url"], "location": m["location"], "posted": m.get("posted", "")}
                           for m in members[1:]]
        lead["is_new"] = any(m.get("is_new") for m in members)
        out.append(lead)
    return out


class Search:
    """A saved search. mode 'it' = built-in IT profile; mode 'keywords' = any of the keywords."""

    def __init__(self, row: dict):
        self.id = row["id"]
        self.name = row["name"]
        self.mode = row.get("mode", "keywords")
        self.keywords = row.get("keywords") or []
        self.exclude = row.get("exclude") or []
        self.categories = set(row.get("categories") or [])
        self.search_descriptions = bool(row.get("search_descriptions"))
        self._kw = _keyword_regex(self.keywords)
        self._ex = _keyword_regex(self.exclude)

    def match(self, job: dict):
        """Return {'track', 'score', 'tags'} if the job matches, else None."""
        title = job["title"]
        if self.categories and job["category"] not in self.categories:
            return None
        haystack = title + ("\n" + job["description"] if self.search_descriptions and job.get("description") else "")
        if self._ex and self._ex.search(haystack):
            return None
        if self.mode == "it":
            hit = classify_it(title)
            if not hit and self._kw and self._kw.search(haystack):  # extra keywords widen the IT profile
                hit = ("Custom keyword", 70)
            if not hit:
                return None
            track, score = hit
        else:
            if not self._kw or not self._kw.search(haystack):
                return None
            track = (classify_it(title) or ("Keyword match", 0))[0]
            score = 75 if self._kw.search(title) else 60  # title hits rank above description-only hits
        adj, tags = level_tags(title)
        return {"track": track, "score": score + adj, "tags": tags}
