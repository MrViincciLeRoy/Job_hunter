"""
apps/accounts/cv_extractor.py

Pure local CV extraction — no external API.
Uses pdfplumber / pypdf for text then layered regex + heuristics.
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any


# ── Text extraction ────────────────────────────────────────────────────────────

def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages = []
            for p in pdf.pages:
                text = p.extract_text(x_tolerance=2, y_tolerance=3) or ""
                pages.append(text)
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
        import docx2txt
        return docx2txt.process(io.BytesIO(file_bytes))
    except Exception:
        pass
    return file_bytes.decode("utf-8", errors="ignore")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _lines(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if l.strip()]

def _norm(text: str) -> str:
    """Normalise unicode dashes/bullets to ASCII."""
    return (text
        .replace("\u2013", "-").replace("\u2014", "-")
        .replace("\u2022", "*").replace("\u2019", "'")
        .replace("\u00a0", " ").replace("\uf0b7", "*")
    )


# ── Section splitter ───────────────────────────────────────────────────────────

# All known section headers (order matters for greedy matching)
_ALL_HEADERS = [
    "WORK EXPERIENCE", "PROFESSIONAL EXPERIENCE", "EMPLOYMENT HISTORY",
    "CAREER HISTORY", "EXPERIENCE",
    "EDUCATION AND TRAINING", "EDUCATION & TRAINING", "ACADEMIC BACKGROUND",
    "ACADEMIC QUALIFICATIONS", "QUALIFICATIONS", "EDUCATION",
    "TECHNICAL SKILLS", "CORE COMPETENCIES", "KEY COMPETENCIES",
    "COMPUTER SKILLS", "IT SKILLS", "COMPETENCIES", "SKILLS",
    "LANGUAGE PROFICIENCY", "LANGUAGES SPOKEN", "LANGUAGES",
    "PROFESSIONAL REFERENCES", "CHARACTER REFERENCES", "REFERENCES",
    "PROFESSIONAL SUMMARY", "EXECUTIVE SUMMARY", "CAREER OBJECTIVE",
    "CAREER SUMMARY", "PROFILE SUMMARY", "PERSONAL PROFILE",
    "OBJECTIVE", "SUMMARY", "PROFILE", "ABOUT ME", "ABOUT",
    "CERTIFICATIONS", "CERTIFICATES", "ACHIEVEMENTS", "AWARDS",
    "PROJECTS", "VOLUNTEER", "INTERESTS", "HOBBIES",
    "PERSONAL DETAILS", "PERSONAL INFORMATION", "CONTACT DETAILS", "CONTACT",
]

_HEADER_PAT = re.compile(
    r"(?:^|\n)\s*(" + "|".join(re.escape(h) for h in _ALL_HEADERS) + r")\s*[:\-]?\s*\n",
    re.I | re.M,
)


def _get_section(text: str, *names: str) -> str:
    """Return text between the first matching header and the next known header."""
    text = _norm(text)
    pat = re.compile(
        r"(?:^|\n)\s*(?:" + "|".join(re.escape(n) for n in names) + r")\s*[:\-]?\s*\n([\s\S]*?)(?=\n\s*(?:" +
        "|".join(re.escape(h) for h in _ALL_HEADERS) + r")\s*[:\-]?\s*\n|$)",
        re.I | re.M,
    )
    m = pat.search(text)
    return m.group(1).strip() if m else ""


# ── Contact info ───────────────────────────────────────────────────────────────

_EMAIL_RE    = re.compile(r"[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,}")
_PHONE_RE    = re.compile(
    r"(?:\+?27|0)[\s.\-]?(?:(?:6[0-9]|7[0-9]|8[0-9])[\s.\-]?\d{3}[\s.\-]?\d{4}"
    r"|(?:1[0-9]|2[0-9]|3[0-9]|4[0-9]|5[0-9])[\s.\-]?\d{3}[\s.\-]?\d{4})"
    r"|\+\d{1,3}[\s.\-]?\(?\d{1,4}\)?[\s.\-]?\d{3}[\s.\-]?\d{3,4}"
)
_LINKEDIN_RE = re.compile(r"linkedin\.com/in/([\w\-]+)", re.I)
_GITHUB_RE   = re.compile(r"github\.com/([\w\-]+)", re.I)
_URL_RE      = re.compile(r"https?://[\w./\-?=&%+#@:]+")


def _extract_email(text: str) -> str:
    m = _EMAIL_RE.search(text)
    return m.group() if m else ""


def _extract_phone(text: str) -> str:
    m = _PHONE_RE.search(text)
    return re.sub(r"[\s.\-]", " ", m.group()).strip() if m else ""


def _extract_linkedin(text: str) -> str:
    m = _LINKEDIN_RE.search(text)
    return f"https://linkedin.com/in/{m.group(1)}" if m else ""


def _extract_github(text: str) -> str:
    m = _GITHUB_RE.search(text)
    return f"https://github.com/{m.group(1)}" if m else ""


def _extract_portfolio(text: str) -> str:
    for u in _URL_RE.findall(text):
        if not any(x in u.lower() for x in ("linkedin", "github", "mailto", "facebook", "twitter", "instagram")):
            return u
    return ""


# ── Name ──────────────────────────────────────────────────────────────────────

_NAME_RE = re.compile(r"^[A-Z][a-zA-Z'\-]{1,30}(?:\s+[A-Z][a-zA-Z'\-]{1,30}){1,4}$")


def _extract_name(lines: list[str]) -> tuple[str, str]:
    for line in lines[:10]:
        line = _clean(line)
        if not line or "@" in line or re.search(r"\d", line) or len(line) > 60:
            continue
        if _NAME_RE.match(line):
            parts = line.split()
            return parts[0], " ".join(parts[1:])
    return "", ""


# ── Location ──────────────────────────────────────────────────────────────────

_SA_PLACES = re.compile(
    r"\b(johannesburg|cape town|durban|pretoria|port elizabeth|gqeberha|"
    r"bloemfontein|nelspruit|mbombela|polokwane|east london|kimberley|"
    r"rustenburg|soweto|tshwane|sandton|randburg|centurion|midrand|"
    r"roodepoort|benoni|boksburg|germiston|witbank|emalahleni|"
    r"gauteng|western cape|kwazulu.natal|limpopo|mpumalanga|"
    r"north west|northern cape|free state|eastern cape)\b",
    re.I,
)


def _extract_location(lines: list[str], text: str) -> str:
    # Prefer lines near the top that contain SA place names
    for line in lines[:25]:
        if _SA_PLACES.search(line):
            cleaned = re.sub(r"[\|•:]+", ",", line)
            # Strip contact noise
            if "@" not in cleaned and not _PHONE_RE.search(cleaned):
                return _clean(cleaned)
    # Fallback: "City, Province" or "City, Country"
    m = re.search(r"\b([A-Z][a-zA-Z\s]{2,20}),\s*([A-Z]{2}|[A-Z][a-zA-Z\s]{3,20})\b", text[:800])
    return _clean(m.group()) if m else ""


# ── Bio / Summary ──────────────────────────────────────────────────────────────

def _extract_bio(text: str) -> str:
    section = _get_section(
        text,
        "PROFESSIONAL SUMMARY", "EXECUTIVE SUMMARY", "CAREER SUMMARY",
        "PERSONAL PROFILE", "PROFILE SUMMARY", "SUMMARY", "PROFILE",
        "OBJECTIVE", "CAREER OBJECTIVE", "ABOUT ME", "ABOUT",
    )
    if section:
        # Remove stray header lines, cap at 600 chars
        lines = [l for l in section.splitlines() if l.strip() and len(l.strip()) > 15]
        return _clean(" ".join(lines))[:600]
    return ""


# ── Occupation ─────────────────────────────────────────────────────────────────

_TITLE_WORDS = re.compile(
    r"\b(developer|engineer|designer|manager|analyst|consultant|architect|"
    r"specialist|officer|director|lead|head|accountant|administrator|"
    r"coordinator|technician|programmer|scientist|researcher|teacher|"
    r"lecturer|nurse|doctor|pharmacist|attorney|lawyer|sales|marketing|"
    r"recruiter|hr|human resources|finance|legal|buyer|planner|"
    r"supervisor|foreman|driver|mechanic|electrician|plumber|welder|"
    r"receptionist|clerk|assistant|intern|graduate|trainee)\b",
    re.I,
)


def _extract_occupation(lines: list[str], name: str) -> str:
    name_words = {w.lower() for w in name.split()}
    for line in lines[:20]:
        lc = line.lower()
        if _TITLE_WORDS.search(lc) and not (name_words & set(lc.split())) and len(line) < 80:
            return _clean(line)
    return ""


# ── Years experience ───────────────────────────────────────────────────────────

def _infer_years_experience(text: str, work_experiences: list[dict]) -> str:
    m = re.search(r"\b(\d+)\+?\s*years?\s+(?:of\s+)?(?:work\s+)?experience", text, re.I)
    if m:
        n = int(m.group(1))
        if n < 1:   return "0-1"
        if n <= 2:  return "1-2"
        if n <= 5:  return "3-5"
        if n <= 10: return "5-10"
        return "10+"
    years = []
    for we in work_experiences:
        sd = we.get("start_date", "")
        try:
            years.append(int(sd[:4]))
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


# ── Date parsing ───────────────────────────────────────────────────────────────

_MONTHS = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
    "january":1,"february":2,"march":3,"april":4,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}

_DATE_TOKEN = (
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}"  # Month YYYY
    r"|\d{1,2}[/\-\.]\d{4}"                                                       # MM/YYYY
    r"|\d{4})"                                                                     # YYYY
)
_DATE_RANGE_RE = re.compile(
    rf"({_DATE_TOKEN})\s*[-–—to/]+\s*({_DATE_TOKEN}|Present|Current|Now|Till\s*Date|To\s*Date|Date)",
    re.I,
)


def _parse_date(s: str) -> str:
    s = s.strip()
    if re.match(r"^\d{4}$", s):
        return f"{s}-01-01"
    m = re.match(r"([A-Za-z]+)[\s.]+(\d{4})", s)
    if m:
        month = _MONTHS.get(m.group(1)[:3].lower(), 1)
        return f"{m.group(2)}-{month:02d}-01"
    m = re.match(r"(\d{1,2})[/\-.](\d{4})", s)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}-01"
    return ""


def _is_present(s: str) -> bool:
    return bool(re.match(r"present|current|now|till\s*date|to\s*date|date", s.strip(), re.I))


# ── Work Experience ────────────────────────────────────────────────────────────

_EXP_SECTION_NAMES = (
    "WORK EXPERIENCE", "PROFESSIONAL EXPERIENCE", "EMPLOYMENT HISTORY",
    "CAREER HISTORY", "EXPERIENCE",
)

_EMP_TYPES = re.compile(
    r"\b(full[- ]time|part[- ]time|contract|freelance|temporary|temp|"
    r"fixed[- ]term|internship|intern|learnership|graduate|volunteer)\b",
    re.I,
)


def _extract_work_experiences(text: str) -> list[dict]:
    text = _norm(text)
    section = _get_section(text, *_EXP_SECTION_NAMES) or text

    # Split into blocks — each starts when we find a date range or a clear title line
    # Strategy: find all date-range positions, then carve out blocks around them
    entries: list[dict] = []
    seen_ranges: set[tuple] = set()

    for dm in _DATE_RANGE_RE.finditer(section):
        start_raw = dm.group(1)
        end_raw   = dm.group(2)
        start_str = _parse_date(start_raw)
        is_cur    = _is_present(end_raw)
        end_str   = None if is_cur else _parse_date(end_raw)

        key = (start_str, end_str)
        if key in seen_ranges:
            continue
        seen_ranges.add(key)

        # Grab context: ~8 lines before the date range
        pre_text  = section[:dm.start()]
        pre_lines = [l.strip() for l in pre_text.splitlines() if l.strip()][-8:]
        post_text = section[dm.end():]
        post_lines= [l.strip() for l in post_text.splitlines() if l.strip()][:10]

        job_title, company, location, emp_type = "", "", "", ""
        desc_lines: list[str] = []

        # Job title is usually the last non-empty pre-line before the date
        # Company is the line before that, or same line split by " at "/" @ "
        if pre_lines:
            top = pre_lines[-1]
            # "Job Title at Company" / "Job Title @ Company" / "Job Title, Company"
            sep = re.split(r"\s+(?:at|@|–)\s+|\s*,\s*(?=[A-Z])", top, maxsplit=1)
            if len(sep) == 2 and len(sep[1]) < 80:
                job_title = _clean(sep[0])
                company   = _clean(sep[1])
            else:
                job_title = _clean(top)
                if len(pre_lines) >= 2:
                    company = _clean(pre_lines[-2])

        # Employment type from post context
        full_context = " ".join(pre_lines + post_lines)
        em = _EMP_TYPES.search(full_context)
        if em:
            emp_type = em.group(1).title()

        # Location: look for "City, Province" in surrounding lines
        for l in (pre_lines + post_lines)[:5]:
            if _SA_PLACES.search(l) or re.search(r"[A-Z][a-z]+,\s*[A-Z]{2,}", l):
                if l != job_title and l != company:
                    location = _clean(l)
                    break

        # Description: bullet lines after the date
        for l in post_lines:
            stripped = l.lstrip("*•-–>◦▪▸ ")
            if stripped and len(stripped) > 10 and not _DATE_RANGE_RE.search(l):
                desc_lines.append(stripped)
            if len(desc_lines) >= 5:
                break

        # Skip if we couldn't find a job title
        if not job_title and not company:
            continue
        # Skip obvious false positives (education dates etc.)
        if re.search(r"\b(university|college|diploma|degree|certificate|school)\b", job_title, re.I):
            continue

        entries.append({
            "job_title":       job_title[:150],
            "company":         company[:150],
            "location":        location[:100],
            "employment_type": emp_type,
            "start_date":      start_str,
            "end_date":        end_str,
            "is_current":      is_cur,
            "description":     _clean(" ".join(desc_lines))[:500],
        })

    # Deduplicate by (title, company) keeping longest description
    seen: dict[tuple, dict] = {}
    for e in entries:
        k = (e["job_title"].lower(), e["company"].lower())
        if k not in seen or len(e["description"]) > len(seen[k]["description"]):
            seen[k] = e

    return sorted(seen.values(), key=lambda x: x["start_date"] or "", reverse=True)[:12]


# ── Education ──────────────────────────────────────────────────────────────────

_NQF_MAP = {
    "10": ["phd","doctoral","doctorate","d.phil","dphil"],
    "9":  ["masters","master of","m.sc","msc","mba","m.com","mcom","m.eng","meng","m.tech","mtech","llm"],
    "8":  ["honours","hons","postgraduate diploma","pgdip","postgrad dip"],
    "7":  ["bachelor","b.sc","bsc","b.com","bcom","b.tech","btech","b.eng","beng","b.a","ba ","llb","degree"],
    "6":  ["national diploma","nd ","diploma"],
    "5":  ["higher certificate","higher cert"],
    "4":  ["matric","grade 12","national senior certificate","nsc","senior certificate"],
}

_INST_RE = re.compile(
    r"\b(university|universiteit|college|institute|school|academy|"
    r"polytechnic|tvet|varsity|faculty|campus|seta)\b", re.I,
)


def _infer_nqf(qual: str) -> str:
    lc = qual.lower()
    for level, kws in _NQF_MAP.items():
        if any(kw in lc for kw in kws):
            return level
    return ""


def _extract_educations(text: str) -> list[dict]:
    text = _norm(text)
    section = _get_section(
        text,
        "EDUCATION AND TRAINING", "EDUCATION & TRAINING",
        "ACADEMIC BACKGROUND", "ACADEMIC QUALIFICATIONS",
        "QUALIFICATIONS", "EDUCATION",
    )
    if not section:
        return []

    year_re  = re.compile(r"\b((?:19|20)\d{2})\b")
    entries: list[dict] = []

    # Split on blank lines or year anchors
    blocks = re.split(r"\n{2,}|\n(?=\s*(?:19|20)\d{2})", section)

    for block in blocks:
        block = block.strip()
        if not block or len(block) < 10:
            continue

        lines  = [l.strip() for l in block.splitlines() if l.strip()]
        years  = year_re.findall(block)
        start_year = int(years[0]) if years else 0
        end_year   = int(years[-1]) if len(years) > 1 else None
        is_current = bool(re.search(r"present|current|ongoing|in progress", block, re.I))
        if is_current:
            end_year = None

        qual = _clean(lines[0]) if lines else ""
        inst = _clean(lines[1]) if len(lines) > 1 else ""
        desc_lines = lines[2:]

        # Swap if institution keyword found in qual
        if _INST_RE.search(qual) and not _INST_RE.search(inst):
            qual, inst = inst, qual

        # Extract field of study from "BSc in Computer Science" pattern
        field = ""
        fom = re.search(r"\bin\s+([A-Z][a-zA-Z\s&]+)", qual)
        if fom:
            field = _clean(fom.group(1))

        nqf = _infer_nqf(qual) or _infer_nqf(inst)

        if not qual and not inst:
            continue

        entries.append({
            "institution":    inst[:200],
            "qualification":  qual[:200],
            "field_of_study": field[:150],
            "nqf_level":      nqf,
            "start_year":     start_year,
            "end_year":       end_year,
            "is_current":     is_current,
            "description":    _clean(" ".join(desc_lines[:3]))[:300],
        })

    return entries[:8]


# ── Skills ─────────────────────────────────────────────────────────────────────

_LEVEL_RE = re.compile(
    r"\b(expert|advanced|proficient|strong|solid|good|intermediate|"
    r"working knowledge|familiar|basic|beginner|entry[- ]level)\b", re.I,
)
_LEVEL_MAP = {
    "expert":"expert","advanced":"advanced","proficient":"advanced",
    "strong":"advanced","solid":"advanced","good":"intermediate",
    "intermediate":"intermediate","working knowledge":"intermediate",
    "familiar":"intermediate","basic":"beginner","beginner":"beginner",
    "entry-level":"beginner","entry level":"beginner",
}

_TECH_RE = re.compile(
    r"\b(python|java(?:script)?|typescript|c\+\+|c#|php|ruby|swift|kotlin|"
    r"go(?:lang)?|rust|scala|r(?:\s+language)?|matlab|bash|shell|powershell|"
    r"html5?|css3?|react(?:\.js)?|vue(?:\.js)?|angular(?:js)?|next(?:\.js)?|"
    r"node(?:\.js)?|express(?:\.js)?|django|flask|fastapi|spring(?:\s+boot)?|"
    r"laravel|rails|asp\.net|\.net|"
    r"sql|mysql|postgresql|sqlite|mongodb|redis|elasticsearch|firebase|"
    r"aws|azure|gcp|google cloud|heroku|vercel|netlify|"
    r"docker|kubernetes|terraform|ansible|jenkins|gitlab(?:\s+ci)?|github(?:\s+actions)?|"
    r"git|linux|ubuntu|debian|centos|windows\s+server|"
    r"excel|word|powerpoint|outlook|office\s+365|google\s+workspace|"
    r"sap|erp|sage|xero|quickbooks|pastel|"
    r"illustrator|photoshop|figma|sketch|canva|indesign|autocad|solidworks|"
    r"machine\s+learning|deep\s+learning|tensorflow|pytorch|scikit|keras|"
    r"pandas|numpy|matplotlib|power\s+bi|tableau|looker|"
    r"jira|confluence|trello|asana|monday|slack|teams|zoom)\b",
    re.I,
)


def _extract_skills(text: str) -> list[dict]:
    text = _norm(text)
    section = _get_section(
        text,
        "TECHNICAL SKILLS", "CORE COMPETENCIES", "KEY COMPETENCIES",
        "COMPUTER SKILLS", "IT SKILLS", "COMPETENCIES", "SKILLS",
    )
    source = section or text

    found: dict[str, dict] = {}

    # 1. Known tech terms
    for m in _TECH_RE.finditer(source):
        name = _clean(m.group())
        ctx  = source[max(0,m.start()-40):m.end()+40]
        lm   = _LEVEL_RE.search(ctx)
        level = _LEVEL_MAP.get((lm.group(1).lower() if lm else "").replace("-"," "), "intermediate")
        key  = name.lower()
        if key not in found:
            found[key] = {"name": name.title(), "level": level, "category": "Technical"}

    # 2. Comma/bullet/pipe lists in the skills section
    if section:
        # Handle "Category: skill1, skill2" patterns
        for cat_match in re.finditer(r"^([A-Z][A-Za-z\s/&]{2,30}):\s*(.+)$", section, re.M):
            cat_name = _clean(cat_match.group(1))
            items    = re.split(r"[,;|•\n]+", cat_match.group(2))
            for item in items:
                item = _clean(item.lstrip("*•-– "))
                if 2 < len(item) < 60 and not re.search(r"\d{4}", item):
                    lm    = _LEVEL_RE.search(item)
                    level = _LEVEL_MAP.get((lm.group(1).lower() if lm else "").replace("-"," "), "intermediate")
                    clean_name = _LEVEL_RE.sub("", item).strip(" ()")
                    key = clean_name.lower()
                    if key and key not in found and len(key) > 1:
                        found[key] = {"name": clean_name.title(), "level": level, "category": cat_name}

        # Plain list items
        plain = _TECH_RE.sub("", section)
        for item in re.split(r"[,•|\n/;]+", plain):
            item = _clean(item.lstrip("*•-–> "))
            if 2 < len(item) < 60 and not re.search(r"\d{4}", item):
                lm    = _LEVEL_RE.search(item)
                level = _LEVEL_MAP.get((lm.group(1).lower() if lm else "").replace("-"," "), "intermediate")
                clean_name = _LEVEL_RE.sub("", item).strip(" ()")
                key = clean_name.lower()
                if key and key not in found and len(key) > 1:
                    found[key] = {"name": clean_name.title(), "level": level, "category": ""}

    return list(found.values())[:35]


# ── Languages ──────────────────────────────────────────────────────────────────

# All 11 SA official + common international languages
_LANG_LIST = [
    "english","afrikaans","zulu","isizulu","xhosa","isixhosa","sotho","sesotho",
    "tswana","setswana","venda","tshivenda","tsonga","xitsonga","swati","siswati",
    "ndebele","isindebele","pedi","sepedi",
    "french","spanish","portuguese","mandarin","cantonese","arabic","hindi",
    "urdu","german","italian","dutch","russian","japanese","korean",
]

_PROF_MAP = {
    "native":"native","mother tongue":"native","home language":"native",
    "first language":"native","fluent":"native","bilingual":"native",
    "professional":"professional","business":"professional","advanced":"professional",
    "full professional":"professional",
    "conversational":"conversational","intermediate":"conversational",
    "working":"conversational","limited working":"conversational",
    "basic":"basic","elementary":"basic","beginner":"basic","some":"basic",
}

_LANG_RE = re.compile(
    r"\b(" + "|".join(re.escape(l) for l in _LANG_LIST) + r")\b"
    r"(?:"
    r"\s*[-:–(]+\s*([A-Za-z\s]+?)(?:[,;\n)]|$)"   # English - Native  or  English (Fluent)
    r"|"
    r"\s*\(([^)]+)\)"                              # English (Native Speaker)
    r")?",
    re.I,
)


def _extract_languages(text: str) -> list[dict]:
    text = _norm(text)
    section = _get_section(text, "LANGUAGE PROFICIENCY", "LANGUAGES SPOKEN", "LANGUAGES")
    source  = section if section else text[:3000]

    found: dict[str, dict] = {}

    for m in _LANG_RE.finditer(source):
        lang = m.group(1).title()
        # Normalise isiZulu → Zulu etc.
        lang = re.sub(r"^(?:Isi|Se|Si|Tshi|Xi)", "", lang, flags=re.I).strip().title()
        if not lang:
            continue

        # Proficiency from inline tag or nearby text
        raw_prof = (m.group(2) or m.group(3) or "").strip().lower()
        # If no inline tag, look for proficiency word within 40 chars
        if not raw_prof:
            ctx = source[m.start():m.start()+60].lower()
            for kw in _PROF_MAP:
                if kw in ctx:
                    raw_prof = kw
                    break

        proficiency = "professional"
        for kw, val in _PROF_MAP.items():
            if kw in raw_prof:
                proficiency = val
                break

        key = lang.lower()
        if key not in found:
            found[key] = {"name": lang, "proficiency": proficiency}

    # Fallback: scan lines in the section for "Language: Level" pattern
    if section:
        for line in _lines(section):
            m2 = re.match(r"([A-Za-z]{3,})\s*[-:–]\s*([A-Za-z\s]+)", line)
            if m2:
                lang_cand = m2.group(1).strip().title()
                prof_cand = m2.group(2).strip().lower()
                if lang_cand.lower() in _LANG_LIST:
                    key = lang_cand.lower()
                    proficiency = "professional"
                    for kw, val in _PROF_MAP.items():
                        if kw in prof_cand:
                            proficiency = val
                            break
                    if key not in found:
                        found[key] = {"name": lang_cand, "proficiency": proficiency}

    return list(found.values())[:12]


# ── References ─────────────────────────────────────────────────────────────────

_RELATIONSHIP_RE = re.compile(
    r"\b(line manager|direct manager|reporting manager|senior manager|hr manager|"
    r"human resources|supervisor|director|colleague|peer|mentor|coach|"
    r"client|customer|lecturer|professor|academic)\b",
    re.I,
)


def _extract_references(text: str) -> list[dict]:
    text = _norm(text)
    section = _get_section(text, "PROFESSIONAL REFERENCES", "CHARACTER REFERENCES", "REFERENCES")

    if not section:
        return []
    if re.search(r"available\s+(?:on|upon)\s+request|furnished\s+upon|upon\s+request", section, re.I):
        return []

    entries: list[dict] = []

    # Split on double newlines or lines that look like a new name (title-case, no digits)
    blocks = re.split(r"\n{2,}", section.strip())

    for block in blocks:
        block = block.strip()
        if not block or len(block) < 10:
            continue

        lines  = [l.strip() for l in block.splitlines() if l.strip()]
        email  = _extract_email(block)
        phone  = _extract_phone(block)

        name = position = company = relationship = ""

        # Try "Name: John Smith" style first
        for line in lines:
            km = re.match(r"(?:name|person|contact)\s*[:\-]\s*(.+)", line, re.I)
            if km:
                name = _clean(km.group(1))
                break
            tm = re.match(r"(?:title|position|designation|job title)\s*[:\-]\s*(.+)", line, re.I)
            if tm:
                position = _clean(tm.group(1))
            cm = re.match(r"(?:company|organisation|organization|employer|firm)\s*[:\-]\s*(.+)", line, re.I)
            if cm:
                company = _clean(cm.group(1))
            rm = re.match(r"(?:relationship|capacity)\s*[:\-]\s*(.+)", line, re.I)
            if rm:
                relationship = _clean(rm.group(1))

        # Fallback: first non-contact line is the name
        if not name:
            for line in lines:
                if "@" not in line and not _PHONE_RE.search(line) and not re.search(r"\d{4}", line):
                    if _NAME_RE.match(line):
                        name = _clean(line)
                        break

        # Position / company from following lines
        if not position and len(lines) > 1:
            for line in lines[1:]:
                if line != name and "@" not in line and not _PHONE_RE.search(line):
                    if not position:
                        position = _clean(line)
                    elif not company:
                        company = _clean(line)
                    else:
                        break

        # Relationship from any line
        for line in lines:
            rm = _RELATIONSHIP_RE.search(line)
            if rm and not relationship:
                relationship = rm.group(1).title()
                break

        if not name:
            continue

        entries.append({
            "name":         name[:150],
            "position":     position[:150],
            "company":      company[:150],
            "relationship": relationship[:100],
            "email":        email,
            "phone":        phone,
        })

    return entries[:5]


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_cv(file_bytes: bytes, mime_type: str = "application/pdf") -> dict[str, Any]:
    if "pdf" in mime_type:
        text = extract_text_from_pdf(file_bytes)
    elif "image" in mime_type:
        return _empty()
    else:
        text = extract_text_from_docx(file_bytes)

    if not text.strip():
        return _empty()

    text  = _norm(text)
    lines = _lines(text)

    email      = _extract_email(text)
    phone      = _extract_phone(text)
    first, last= _extract_name(lines)
    location   = _extract_location(lines, text)
    linkedin   = _extract_linkedin(text)
    github     = _extract_github(text)
    portfolio  = _extract_portfolio(text)
    bio        = _extract_bio(text)
    occupation = _extract_occupation(lines, f"{first} {last}")
    experiences= _extract_work_experiences(text)
    educations = _extract_educations(text)
    skills     = _extract_skills(text)
    languages  = _extract_languages(text)
    references = _extract_references(text)
    years_exp  = _infer_years_experience(text, experiences)

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
        "first_name":"","last_name":"","phone":"","location":"",
        "occupation":"","years_experience":"","bio":"",
        "linkedin_url":"","github_url":"","portfolio_url":"",
        "work_experiences":[],"educations":[],"skills":[],
        "languages":[],"references":[],
    }
