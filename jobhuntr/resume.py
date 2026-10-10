"""Read resume text out of uploaded files and build the profile used for job matching."""
import io
import re
import zipfile

from . import skills


def text_from_file(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader  # imported lazily so the app starts fast
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if name.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", "ignore")
    raise ValueError("Use a .pdf, .docx or .txt file (or paste the text)")


def build_profile(resume_text: str, extra: str) -> dict:
    """extra = comma-separated skills/certs the resume doesn't mention (e.g. 'Security+ (in progress), Splunk')."""
    extra_list = [x.strip() for x in (extra or "").split(",") if x.strip()]
    found = skills.find_skills(resume_text) + skills.find_skills(", ".join(extra_list))
    return {"resume_text": resume_text or "", "extra": extra or "", "skills": sorted(set(found)),
            "words": len((resume_text or "").split())}
