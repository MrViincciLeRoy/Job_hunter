"""
apps/accounts/cv_extractor.py

Local CV extraction — no external API.
Uses pdfplumber for text, then a layered regex/heuristic algo.

Returned dict shape matches the Anthropic-extraction schema exactly,
so the onboarding front-end works without changes.
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any

# ── PDF text extraction ────────────────────────────────────────────────────────

def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        return "\n".join(pages)
    except Exception:
        pass
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception:
        pass
    return ""


def extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        import docx2txt, io as _io
        return docx2txt.process(_io.BytesIO(file_bytes))
    except Exception:
        return file_bytes.decode("utf-8", errors="ignore")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def _lines(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if l.strip()]

def _section_text(text: str, *headers: str, stop_headers: list[str] | None = None) -> str:
    """
    Extract text between a section header and the next known section header.
    Case-insensitive. Returns empty string if not found.
    """
    stop = stop_headers or SECTION_HEADERS
    pattern = r"(?i)(?:^|\n)(?:" + "|".join(re.escape(h) for h in headers) + r")\s*[:\-]?\s*\n([\s\S]*?)(?=\n(?:" + "|".join(re.escape(s) for s in stop) + r")\s*[:\-]?\s*\n|$)"
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ""


SECTION_HEADERS = [
    "EXPERIENCE", "WORK EXPERIENCE", "EMPLOYMENT", "EMPLOYMENT HISTORY",
    "PROFESSIONAL EXPERIENCE", "CAREER HISTORY",
    "EDUCATION", "QUALIFICATIONS", "ACADEMIC",
    "SKILLS", "TECHNICAL SKILLS", "CORE COMPETENCIES", "COMPETENCIES",
    "LANGUAGES", "LANGUAGE PROFICIENCY",
    "REFERENCES", "REFEREES",
    "SUMMARY", "PROFILE", "OBJECTIVE", "ABOUT",
    "CERTIFICATIONS", "CERTIFICATES", "ACHIEVEMENTS",
    "PROJECTS", "INTERESTS", "HOBBIES",
    "CONTACT", "PERSONAL DETAILS", "PERSONAL INFORMATION",
]


# ── Contact / Personal ─────────────────────────────────────────────────────────

EMAIL_RE    = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
PHONE_RE    = re.compile(r"(?:\+?27|0)[\s\-]?[6-8]\d[\s\-]?\d{3}[\s\-]?\d{4}|\+?\d[\d\s\-().]{8,15}")
LINKEDIN_RE = re.compile(r"(?:linkedin\.com/in/)([\w\-]+)", re.I)
GITHUB_RE   = re.compile(r"(?:github\.com/)([\w\-]+)", re.I)
URL_RE      = re.compile(r"https?://[\w./\-?=&%+#]+")


def _extract_email(text: str) -> str:
    m = EMAIL_RE.search(text)
    return m.group() if m else ""


def _extract_phone(text: str) -> str:
    m = PHONE_RE.search(text)
    return _clean(m.group()) if m else ""


def _extract_linkedin(text: str) -> str:
    m = LINKEDIN_RE.search(text)
    return f"https://linkedin.com/in/{m.group(1)}" if m else ""


def _extract_github(text: str) -> str:
    m = GITHUB_RE.search(text)
    return f"https://github.com/{m.group(1)}" if m else ""


def _extract_portfolio(text: str) -> str:
    # Return first URL that's not linkedin / github / email
    for u in URL_RE.findall(text):
        if not any(x in u.lower() for x in ("linkedin", "github", "mailto")):
            return u
    return ""


def _extract_name(lines: list[str], email: str) -> tuple[str, str]:
    """
    Heuristic: the name is usually in the first 1-3 non-empty lines,
    is NOT an email/phone/URL, and looks like 2-4 title-case words.
    """
    NAME_RE = re.compile(r"^[A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){1,3}$")
    for line in lines[:8]:
        line = _clean(line)
        if not line or "@" in line or re.search(r"\d{4}", line):
            continue
        if NAME_RE.match(line):
            parts = line.split()
            return parts[0], " ".join(parts[1:])
    return "", ""


def _extract_location(text: str) -> str:
    # Look for "City, Province" or "City, Country" patterns
    LOC_RE = re.compile(
        r"\b([A-Z][a-zA-Z\s]+),\s*([A-Z]{2}|[A-Z][a-zA-Z\s]+)\b"
    )
    # Prioritise lines with common SA cities / provinces
    SA = re.compile(
        r"\b(johannesburg|cape town|durban|pretoria|port elizabeth|gqeberha|bloemfontein|nelspruit|polokwane|east london|kimberley|rustenburg|soweto|tshwane|sandton|randburg|gauteng|western cape|kwazulu|limpopo|mpumalanga|north west|northern cape|free state|eastern cape)\b",
        re.I,
    )
    for line in _lines(text)[:30]:
        if SA.search(line):
            return _clean(line)
    m = LOC_RE.search(text[:500])
    return _clean(m.group()) if m else ""


# ── Summary / Bio ──────────────────────────────────────────────────────────────

def _extract_bio(text: str) -> str:
    block = _section_text(text, "SUMMARY", "PROFILE", "OBJECTIVE", "ABOUT", "PROFESSIONAL SUMMARY")
    if block:
        # Cap at ~500 chars
        return _clean(block[:500])
    return ""


# ── Occupation ─────────────────────────────────────────────────────────────────

TITLES = [
    "developer", "engineer", "designer", "manager", "analyst", "consultant",
    "architect", "specialist", "officer", "director", "lead", "head",
    "accountant", "administrator", "coordinator", "technician", "programmer",
    "scientist", "researcher", "teacher", "lecturer", "nurse", "doctor",
    "sales", "marketing", "recruiter", "hr", "finance", "legal",
]


def _extract_occupation(lines: list[str], name: str) -> str:
    name_words = set(name.lower().split())
    for line in lines[:15]:
        lc = line.lower()
        if any(t in lc for t in TITLES) and not (name_words & set(lc.split())):
            return _clean(line)
    return ""


# ── Years of experience ────────────────────────────────────────────────────────

YR_MAP = [
    (re.compile(r"\b(\d+)\+?\s*years?\s+(?:of\s+)?experience", re.I), None),
]

def _infer_years_experience(text: str, work_experiences: list[dict]) -> str:
    # Try explicit statement first
    m = re.search(r"\b(\d+)\+?\s*years?\s+(?:of\s+)?experience", text, re.I)
    if m:
        n = int(m.group(1))
        if n < 1:   return "0-1"
        if n <= 2:  return "1-2"
        if n <= 5:  return "3-5"
        if n <= 10: return "5-10"
        return "10+"
    # Fall back: calculate from earliest work start
    years: list[int] = []
    for we in work_experiences:
        sd = we.get("start_date", "")
        try:
            y = int(sd[:4])
            years.append(y)
        except Exception:
            pass
    if years:
        span = datetime.today().year - min(years)
        if span < 1:   return "0-1"
        if span <= 2:  return "1-2"
        if span <= 5:  return "3-5"
        if span <= 10: return "5-10"
        return "10+"
    return ""


# ── Work Experience ────────────────────────────────────────────────────────────

DATE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}"
    r"|\d{4})\s*[-–—to]+\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}"
    r"|\d{4}|Present|Current|Now|Date)",
    re.I,
)

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_date_str(s: str) -> str:
    """Convert month-year or year string to YYYY-MM-DD."""
    s = s.strip()
    if re.match(r"^\d{4}$", s):
        return f"{s}-01-01"
    m = re.match(r"([A-Za-z]+)[\s.]+(\d{4})", s)
    if m:
        month_str = m.group(1)[:3].lower()
        month = MONTH_MAP.get(month_str, 1)
        return f"{m.group(2)}-{month:02d}-01"
    return ""


def _extract_work_experiences(text: str) -> list[dict]:
    section = _section_text(
        text,
        "EXPERIENCE", "WORK EXPERIENCE", "EMPLOYMENT",
        "EMPLOYMENT HISTORY", "PROFESSIONAL EXPERIENCE", "CAREER HISTORY",
    )
    if not section:
        section = text  # search whole doc if no clear section

    entries: list[dict] = []
    # Split on date-range anchors
    chunks = re.split(
        r"(?=(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\b\d{4}\s*[-–—])",
        section,
        flags=re.I,
    )

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or len(chunk) < 20:
            continue
        dm = DATE_RE.search(chunk)
        if not dm:
            continue

        start_str = _parse_date_str(dm.group(1))
        end_raw   = dm.group(2)
        is_current = bool(re.match(r"present|current|now|date", end_raw, re.I))
        end_str    = None if is_current else _parse_date_str(end_raw)

        # Remove date from chunk, try to find title + company
        remainder = chunk[:dm.start()] + chunk[dm.end():]
        rem_lines  = [l.strip() for l in remainder.splitlines() if l.strip()]

        job_title = ""
        company   = ""
        location  = ""
        desc_lines: list[str] = []

        if rem_lines:
            # First non-empty line = job title or "Title @ Company" or "Title, Company"
            first = rem_lines[0]
            sep = re.split(r"\s+(?:at|@|,)\s+", first, maxsplit=1, flags=re.I)
            if len(sep) == 2:
                job_title, company = _clean(sep[0]), _clean(sep[1])
            else:
                job_title = _clean(first)
                if len(rem_lines) > 1:
                    company = _clean(rem_lines[1])
                    desc_lines = rem_lines[2:]
                else:
                    desc_lines = []
        else:
            desc_lines = rem_lines

        # Location: look for "City, XX" in the first 3 lines
        for l in rem_lines[:3]:
            if re.search(r"[A-Z][a-z]+,\s*[A-Z]{2,}", l):
                location = _clean(l)
                break

        description = " ".join(desc_lines[:6]).strip()

        if not job_title and not company:
            continue

        entries.append({
            "job_title":   job_title,
            "company":     company,
            "location":    location,
            "start_date":  start_str,
            "end_date":    end_str,
            "is_current":  is_current,
            "description": _clean(description[:400]),
        })

    return entries[:10]  # cap


# ── Education ──────────────────────────────────────────────────────────────────

NQF_KEYWORDS = {
    "10": ["phd", "doctoral", "doctorate", "d.phil"],
    "9":  ["masters", "master of", "m.sc", "mba", "m.com", "m.eng", "m.tech"],
    "8":  ["honours", "hons", "postgraduate diploma", "pgdip"],
    "7":  ["bachelor", "b.sc", "b.com", "b.tech", "b.eng", "b.a ", "degree"],
    "6":  ["diploma", "national diploma", "nd "],
    "5":  ["higher certificate", "higher cert"],
    "4":  ["matric", "grade 12", "national senior certificate", "nsc"],
}


def _infer_nqf(qual: str) -> str:
    lc = qual.lower()
    for level, kws in NQF_KEYWORDS.items():
        if any(kw in lc for kw in kws):
            return level
    return ""


def _extract_educations(text: str) -> list[dict]:
    section = _section_text(
        text,
        "EDUCATION", "QUALIFICATIONS", "ACADEMIC", "ACADEMIC BACKGROUND",
        "EDUCATION AND TRAINING",
    )
    if not section:
        return []

    entries: list[dict] = []
    year_re = re.compile(r"\b((?:19|20)\d{2})\b")

    # Each entry is separated by a blank line or a year anchor
    blocks = re.split(r"\n{2,}|\n(?=(?:19|20)\d{2})", section)

    for block in blocks:
        block = block.strip()
        if not block or len(block) < 8:
            continue
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        years = year_re.findall(block)
        start_year = int(years[0]) if years else 0
        end_year   = int(years[1]) if len(years) > 1 else None
        is_current = bool(re.search(r"present|current|ongoing", block, re.I))
        if is_current:
            end_year = None

        qual = _clean(lines[0]) if lines else ""
        inst = _clean(lines[1]) if len(lines) > 1 else ""
        desc = " ".join(lines[2:]).strip()

        # Swap if institution looks more like an institution name
        INST_WORDS = re.compile(r"\b(university|college|institute|school|academy|polytechnic|tvet)\b", re.I)
        if inst and INST_WORDS.search(qual) and not INST_WORDS.search(inst):
            qual, inst = inst, qual
        if not INST_WORDS.search(inst) and INST_WORDS.search(qual):
            qual, inst = inst, qual

        entries.append({
            "institution":   inst,
            "qualification": qual,
            "field_of_study":"",
            "nqf_level":     _infer_nqf(qual),
            "start_year":    start_year,
            "end_year":      end_year,
            "is_current":    is_current,
            "description":   _clean(desc[:300]),
        })

    return entries[:8]


# ── Skills ─────────────────────────────────────────────────────────────────────

SKILL_LEVEL_RE = re.compile(
    r"\b(expert|advanced|proficient|intermediate|familiar|basic|beginner)\b", re.I
)
LEVEL_MAP = {
    "expert": "expert", "advanced": "advanced", "proficient": "advanced",
    "intermediate": "intermediate", "familiar": "intermediate",
    "basic": "beginner", "beginner": "beginner",
}

TECH_SKILLS = re.compile(
    r"\b(python|java|javascript|typescript|c\+\+|c#|php|ruby|swift|kotlin|go|rust|"
    r"react|vue|angular|django|flask|fastapi|node(?:\.js)?|nextjs|spring|"
    r"sql|mysql|postgresql|mongodb|redis|elasticsearch|"
    r"aws|azure|gcp|docker|kubernetes|terraform|git|linux|"
    r"excel|word|powerpoint|outlook|sap|erp|xero|quickbooks|"
    r"illustrator|photoshop|figma|sketch|autocad|solidworks|"
    r"machine learning|deep learning|tensorflow|pytorch|scikit|pandas|numpy)\b",
    re.I,
)


def _extract_skills(text: str) -> list[dict]:
    section = _section_text(
        text,
        "SKILLS", "TECHNICAL SKILLS", "CORE COMPETENCIES",
        "COMPETENCIES", "TECHNOLOGIES", "TOOLS",
    )
    source = section or text

    found: dict[str, str] = {}

    # 1. Match known tech terms
    for m in TECH_SKILLS.finditer(source):
        skill = _clean(m.group())
        # Look for a level modifier nearby
        context = source[max(0, m.start()-30):m.end()+30]
        lm = SKILL_LEVEL_RE.search(context)
        level = LEVEL_MAP.get(lm.group(1).lower(), "intermediate") if lm else "intermediate"
        found[skill.lower()] = level

    # 2. If skills section exists, also parse comma/bullet lists
    if section:
        # Remove tech already found
        clean_section = TECH_SKILLS.sub("", section)
        # Split on common delimiters
        items = re.split(r"[,•\|\n/;]+", clean_section)
        for item in items:
            item = _clean(item)
            if 2 < len(item) < 50 and not re.search(r"\d{4}", item):
                lm = SKILL_LEVEL_RE.search(item)
                level = LEVEL_MAP.get(lm.group(1).lower(), "intermediate") if lm else "intermediate"
                key = re.sub(SKILL_LEVEL_RE, "", item).strip().lower()
                if key and key not in found:
                    found[key] = level

    return [{"name": k.title(), "level": v, "category": ""} for k, v in found.items()][:30]


# ── Languages ──────────────────────────────────────────────────────────────────

COMMON_LANGS = [
    "english", "afrikaans", "zulu", "xhosa", "sotho", "tswana", "venda",
    "tsonga", "swati", "ndebele", "pedi", "french", "spanish", "portuguese",
    "mandarin", "arabic", "hindi", "german", "italian",
]
PROF_MAP = {
    "native": "native", "fluent": "native", "mother tongue": "native",
    "professional": "professional", "business": "professional",
    "conversational": "conversational", "intermediate": "conversational",
    "basic": "basic", "elementary": "basic",
}


def _extract_languages(text: str) -> list[dict]:
    section = _section_text(text, "LANGUAGES", "LANGUAGE PROFICIENCY", "LANGUAGE SKILLS")
    source = section or text[:1500]

    found: list[dict] = []
    seen: set[str] = set()

    lang_pattern = re.compile(
        r"\b(" + "|".join(COMMON_LANGS) + r")\b(?:[:\s\-–]+([A-Za-z]+))?",
        re.I,
    )
    for m in lang_pattern.finditer(source):
        lang = m.group(1).title()
        if lang.lower() in seen:
            continue
        seen.add(lang.lower())
        prof_word = (m.group(2) or "").lower()
        proficiency = PROF_MAP.get(prof_word, "professional")
        found.append({"name": lang, "proficiency": proficiency})

    return found[:10]


# ── References ─────────────────────────────────────────────────────────────────

def _extract_references(text: str) -> list[dict]:
    section = _section_text(text, "REFERENCES", "REFEREES")
    if not section or re.search(r"available on request|furnished upon", section, re.I):
        return []

    entries: list[dict] = []
    blocks = re.split(r"\n{2,}", section)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        name    = lines[0]
        company = lines[1] if len(lines) > 1 else ""
        pos     = lines[2] if len(lines) > 2 else ""
        email   = _extract_email(block)
        phone   = _extract_phone(block)
        entries.append({
            "name": _clean(name), "company": _clean(company),
            "position": _clean(pos), "email": email, "phone": phone,
        })
    return entries[:5]


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_cv(file_bytes: bytes, mime_type: str = "application/pdf") -> dict[str, Any]:
    """
    Main entry point.  Returns a dict matching the Anthropic-extraction schema.
    """
    # 1. Extract raw text
    if "pdf" in mime_type:
        text = extract_text_from_pdf(file_bytes)
    elif "image" in mime_type:
        # Can't do OCR without tessseract; return empty
        return _empty()
    else:
        text = extract_text_from_docx(file_bytes)

    if not text.strip():
        return _empty()

    lines = _lines(text)

    # 2. Build data
    email         = _extract_email(text)
    phone         = _extract_phone(text)
    first, last   = _extract_name(lines, email)
    location      = _extract_location(text)
    linkedin      = _extract_linkedin(text)
    github        = _extract_github(text)
    portfolio     = _extract_portfolio(text)
    bio           = _extract_bio(text)
    occupation    = _extract_occupation(lines, f"{first} {last}")
    experiences   = _extract_work_experiences(text)
    educations    = _extract_educations(text)
    skills        = _extract_skills(text)
    languages     = _extract_languages(text)
    references    = _extract_references(text)
    years_exp     = _infer_years_experience(text, experiences)

    return {
        "first_name":       first,
        "last_name":        last,
        "phone":            phone,
        "location":         location,
        "occupation":       occupation,
        "years_experience": years_exp,
        "bio":              bio,
        "linkedin_url":     linkedin,
        "github_url":       github,
        "portfolio_url":    portfolio,
        "work_experiences": experiences,
        "educations":       educations,
        "skills":           skills,
        "languages":        languages,
        "references":       references,
    }


def _empty() -> dict[str, Any]:
    return {
        "first_name": "", "last_name": "", "phone": "", "location": "",
        "occupation": "", "years_experience": "", "bio": "",
        "linkedin_url": "", "github_url": "", "portfolio_url": "",
        "work_experiences": [], "educations": [], "skills": [],
        "languages": [], "references": [],
    }
