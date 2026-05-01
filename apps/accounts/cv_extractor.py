from __future__ import annotations
import io, re
from datetime import datetime
from typing import Any


# ── Layout-Aware Text Extraction ───────────────────────────────────────────────

def _extract_blocks(page) -> list[dict]:
    """Get text blocks with bounding box from a PyMuPDF page."""
    raw = page.get_text("blocks")
    blocks = []
    for b in raw:
        text = b[4].strip()
        if not text:
            continue
        blocks.append({"x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3], "text": text})
    return blocks


def _detect_columns(blocks: list[dict], page_width: float) -> list[float]:
    """
    Returns sorted x-boundaries that divide the page into columns.
    Strategy: find large horizontal gaps between block clusters.
    """
    if not blocks:
        return [0, page_width]

    # Collect all x0 values, bucket them into 5px slots
    x_starts = sorted({round(b["x0"] / 5) * 5 for b in blocks})

    # Find gaps > 30px between consecutive x-start clusters
    gaps = []
    for i in range(1, len(x_starts)):
        gap = x_starts[i] - x_starts[i - 1]
        if gap > 30:
            gaps.append((gap, (x_starts[i - 1] + x_starts[i]) / 2))

    if not gaps:
        return [0, page_width]

    # Sort gaps by size desc, take up to 2 largest (3 columns max)
    gaps.sort(reverse=True)
    splits = sorted(mid for _, mid in gaps[:2])
    return [0] + splits + [page_width]


def _blocks_in_band(blocks: list[dict], x_left: float, x_right: float) -> list[dict]:
    """Return blocks whose x0 falls within [x_left, x_right)."""
    return [b for b in blocks if x_left <= b["x0"] < x_right]


def _column_text(blocks: list[dict]) -> str:
    """Sort blocks top-to-bottom and join their text."""
    sorted_blocks = sorted(blocks, key=lambda b: (round(b["y0"] / 4) * 4, b["x0"]))
    lines = []
    for b in sorted_blocks:
        lines.append(b["text"])
    return "\n".join(lines)


def extract_text_layout_aware(file_bytes: bytes) -> str:
    """
    Extract text from a PDF preserving multi-column reading order.
    Uses PyMuPDF block coordinates to detect columns and reconstruct order.
    Falls back to pdfplumber then pypdf.
    """
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        all_pages: list[str] = []

        for page in doc:
            blocks = _extract_blocks(page)
            if not blocks:
                continue

            page_width = page.rect.width
            col_bounds = _detect_columns(blocks, page_width)

            # Check if genuinely multi-column: do columns have meaningful content?
            if len(col_bounds) > 2:
                col_texts = []
                for i in range(len(col_bounds) - 1):
                    band = _blocks_in_band(blocks, col_bounds[i], col_bounds[i + 1])
                    col_text = _column_text(band).strip()
                    if col_text:
                        col_texts.append(col_text)
                # Only use multi-column if each column has real content
                if all(len(t) > 20 for t in col_texts):
                    all_pages.append("\n\n".join(col_texts))
                    continue

            # Single column or columns didn't work — sort everything by y then x
            all_pages.append(_column_text(blocks))

        return "\n\n--- PAGE BREAK ---\n\n".join(all_pages)

    except ImportError:
        pass

    # Fallback 1: pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            return "\n".join(
                p.extract_text(x_tolerance=2, y_tolerance=3) or "" for p in pdf.pages
            )
    except Exception:
        pass

    # Fallback 2: pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception:
        pass

    return ""


def extract_header_area(file_bytes: bytes) -> str:
    """
    Extract text only from the top 30% of the first page.
    Much more reliable for name + contact info since it avoids
    sidebar skills/reference sections that sit at the same y-level.
    """
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page = doc[0]
        page_height = page.rect.height
        cutoff = page_height * 0.30
        blocks = [b for b in _extract_blocks(page) if b["y0"] < cutoff]
        return _column_text(blocks)
    except Exception:
        return ""


def extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        import docx2txt
        return docx2txt.process(io.BytesIO(file_bytes))
    except Exception:
        return file_bytes.decode("utf-8", errors="ignore")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _lines(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if l.strip()]

def _norm(text: str) -> str:
    return (text
            .replace("\u2013", "-").replace("\u2014", "-")
            .replace("\u2022", "*").replace("\u2019", "'")
            .replace("\u00a0", " ").replace("\uf0b7", "*"))


# ── Section Splitter ───────────────────────────────────────────────────────────

_ALL_HEADERS = [
    "WORK EXPERIENCE", "PROFESSIONAL EXPERIENCE", "EMPLOYMENT HISTORY",
    "CAREER HISTORY", "EXPERIENCE", "EDUCATION AND TRAINING",
    "EDUCATION & TRAINING", "ACADEMIC BACKGROUND", "ACADEMIC QUALIFICATIONS",
    "QUALIFICATIONS", "EDUCATION", "TECHNICAL SKILLS", "CORE COMPETENCIES",
    "KEY COMPETENCIES", "COMPUTER SKILLS", "IT SKILLS", "COMPETENCIES",
    "SKILLS", "LANGUAGE PROFICIENCY", "LANGUAGES SPOKEN", "LANGUAGES",
    "PROFESSIONAL REFERENCES", "CHARACTER REFERENCES", "REFERENCES",
    "PROFESSIONAL SUMMARY", "EXECUTIVE SUMMARY", "CAREER OBJECTIVE",
    "CAREER SUMMARY", "PROFILE SUMMARY", "PERSONAL PROFILE", "OBJECTIVE",
    "SUMMARY", "PROFILE", "ABOUT ME", "ABOUT", "CERTIFICATIONS",
    "CERTIFICATES", "ACHIEVEMENTS", "AWARDS", "PROJECTS", "PERSONAL PROJECTS",
    "VOLUNTEER", "INTERESTS", "HOBBIES", "PERSONAL DETAILS",
    "PERSONAL INFORMATION", "CONTACT DETAILS", "CONTACT", "PERSONAL SKILLS",
    "REFERENCE",
]

_HEADER_PAT = re.compile(
    r"(?:^|\n)\s*(?:" + "|".join(re.escape(h) for h in _ALL_HEADERS) + r")\s*[:\-]?\s*(?=\n)",
    re.I,
)


def _get_section(text: str, *names: str) -> str:
    pat = re.compile(
        r"(?:^|\n)\s*(?:" + "|".join(re.escape(n) for n in names) + r")\s*[:\-]?\s*\n"
        r"([\s\S]*?)"
        r"(?=\n\s*(?:" + "|".join(re.escape(h) for h in _ALL_HEADERS) + r")\s*[:\-]?\s*\n|\n---\n|$)",
        re.I,
    )
    m = pat.search(text)
    return m.group(1).strip() if m else ""


def _find_sections(text: str) -> dict[str, str]:
    """
    Split text into named sections. Works even when section headers
    appear anywhere in the text (common in multi-column CVs where the
    extractor may place section titles mid-stream).
    """
    sections: dict[str, str] = {}
    lines = text.splitlines()
    header_re = re.compile(
        r"^\s*(" + "|".join(re.escape(h) for h in _ALL_HEADERS) + r")\s*[:\-]?\s*$",
        re.I,
    )
    current_header = "__preamble__"
    buf: list[str] = []

    for line in lines:
        m = header_re.match(line)
        if m:
            sections[current_header] = "\n".join(buf).strip()
            current_header = m.group(1).upper()
            buf = []
        else:
            buf.append(line)

    sections[current_header] = "\n".join(buf).strip()
    return sections


# ── Contact Info ───────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(
    r"(?:\+?27|0)[\s.\-]?(?:(?:6[0-9]|7[0-9]|8[0-9])[\s.\-]?\d{3}[\s.\-]?\d{4}"
    r"|(?:1[0-9]|2[0-9]|3[0-9]|4[0-9]|5[0-9])[\s.\-]?\d{3}[\s.\-]?\d{4})"
    r"|\+\d{1,3}[\s.\-]?\(?\d{1,4}\)?[\s.\-]?\d{3}[\s.\-]?\d{3,4}"
)
_LINKEDIN_RE = re.compile(r"linkedin\.com/in/([\w\-]+)", re.I)
_GITHUB_RE = re.compile(r"github\.com/([\w\-]+)", re.I)
_URL_RE = re.compile(r"https?://[\w./\-?=&%+#@:]+")


def _extract_email(text: str, header: str = "") -> str:
    # Header area is most reliable (avoids ref emails appearing before candidate's)
    if header:
        m = _EMAIL_RE.search(header)
        if m:
            return m.group()
    ref_pos = re.search(r"\b(REFERENCE|REFERENCES)\b", text, re.I)
    search_text = text[:ref_pos.start()] if ref_pos else text
    m = _EMAIL_RE.search(search_text)
    return m.group() if m else (_EMAIL_RE.search(text).group() if _EMAIL_RE.search(text) else "")

def _extract_phone(text: str, header: str = "") -> str:
    # Header area is most reliable — candidate phone is always in the header
    if header:
        m = _PHONE_RE.search(header)
        if m:
            return re.sub(r"[\s.\-]", " ", m.group()).strip()
    ref_pos = re.search(r"\b(REFERENCE|REFERENCES)\b", text, re.I)
    search_text = text[:ref_pos.start()] if ref_pos else text
    m = _PHONE_RE.search(search_text)
    if m:
        return re.sub(r"[\s.\-]", " ", m.group()).strip()
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
        if not any(x in u.lower() for x in ("linkedin", "github", "mailto", "facebook", "twitter")):
            return u
    return ""


# ── Name ──────────────────────────────────────────────────────────────────────

_NAME_RE = re.compile(r"^[A-Z][a-zA-Z'\-]{1,30}(?:\s+[A-Z][a-zA-Z'\-]{1,30}){1,4}$")
_NAME_CAPS_RE = re.compile(r"^[A-Z]{2,20}(?:\s+[A-Z]{2,20}){1,3}$")
_NAME_PART_RE = re.compile(r"^[A-Z]{2,20}$")  # single ALL-CAPS word like "RONDA"

_SKIP_HEADER = re.compile(
    r"\b(objective|experience|education|skills|reference|contact|"
    r"summary|profile|about|cv|resume|curriculum|personal|details|"
    r"analysis|interpretation|writing|reporting|solving|thinking|"
    r"collaboration|management|intern|assistant|manager|director|"
    r"lecturer|researcher|supervisor)\b", re.I
)

def _extract_name(lines: list[str]) -> tuple[str, str]:
    # First pass: look for full name on one line
    for line in lines[:35]:
        line = _clean(line)
        if not line or "@" in line or len(line) > 65:
            continue
        if re.search(r"\d", line) or _SKIP_HEADER.search(line):
            continue
        if _NAME_RE.match(line) or _NAME_CAPS_RE.match(line):
            parts = line.title().split()
            if len(parts) >= 2:
                return parts[0], " ".join(parts[1:])

    # Second pass: look for two consecutive ALL-CAPS single words (split name)
    for i in range(min(35, len(lines) - 1)):
        a, b = _clean(lines[i]), _clean(lines[i + 1])
        if _NAME_PART_RE.match(a) and _NAME_PART_RE.match(b):
            return a.title(), b.title()

    return "", ""


# ── Location ──────────────────────────────────────────────────────────────────

_SA_PLACES = re.compile(
    r"\b(johannesburg|cape town|durban|pretoria|port elizabeth|gqeberha|"
    r"bloemfontein|nelspruit|mbombela|polokwane|east london|kimberley|"
    r"rustenburg|soweto|tshwane|sandton|randburg|centurion|midrand|"
    r"roodepoort|benoni|boksburg|germiston|witbank|emalahleni|kempton park|"
    r"gauteng|western cape|kwazulu.natal|limpopo|mpumalanga|"
    r"north west|northern cape|free state|eastern cape)\b",
    re.I,
)

def _extract_location(lines: list[str], text: str) -> str:
    for line in lines[:30]:
        if _SA_PLACES.search(line):
            cleaned = re.sub(r"[\|•:]+", ",", line)
            if "@" not in cleaned and not _PHONE_RE.search(cleaned):
                return _clean(cleaned)
    m = re.search(r"\b([A-Z][a-zA-Z\s]{2,20}),\s*([A-Z]{2}|[A-Z][a-zA-Z\s]{3,20})\b", text[:1000])
    return _clean(m.group()) if m else ""


# ── Bio / Summary ──────────────────────────────────────────────────────────────

def _extract_bio(sections: dict[str, str], text: str) -> str:
    for key in ("PROFESSIONAL SUMMARY", "EXECUTIVE SUMMARY", "CAREER SUMMARY",
                "PERSONAL PROFILE", "PROFILE SUMMARY", "SUMMARY", "PROFILE",
                "OBJECTIVE", "CAREER OBJECTIVE", "ABOUT ME", "ABOUT"):
        content = sections.get(key, "")
        if content:
            lines = [l for l in content.splitlines() if l.strip() and len(l.strip()) > 15]
            return _clean(" ".join(lines))[:600]
    # Fallback: look in full text
    return _get_section(text, "OBJECTIVE", "SUMMARY", "PROFILE", "ABOUT")[:600]


# ── Occupation ─────────────────────────────────────────────────────────────────

_TITLE_WORDS = re.compile(
    r"\b(developer|engineer|designer|manager|analyst|consultant|architect|"
    r"specialist|officer|director|lead|head|accountant|administrator|"
    r"coordinator|technician|programmer|scientist|researcher|teacher|"
    r"lecturer|nurse|doctor|pharmacist|attorney|lawyer|sales|marketing|"
    r"recruiter|hr|human resources|finance|legal|buyer|planner|"
    r"supervisor|foreman|driver|mechanic|electrician|plumber|welder|"
    r"receptionist|clerk|assistant|intern|graduate|trainee|chemist)\b",
    re.I,
)

def _extract_occupation(lines: list[str], name: str) -> str:
    name_words = {w.lower() for w in name.split()}
    for line in lines[:25]:
        lc = line.lower()
        if _TITLE_WORDS.search(lc) and not (name_words & set(lc.split())) and len(line) < 80:
            # Skip if it looks like a section header
            if not re.match(r"^(EXPERIENCE|EDUCATION|SKILLS|REFERENCE)", line, re.I):
                return _clean(line)
    return ""


# ── Date Parsing ───────────────────────────────────────────────────────────────

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

_DATE_TOKEN = (
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}"
    r"|\d{1,2}[/\-\.]\d{4}"
    r"|\d{4})"
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

_EMP_TYPES = re.compile(
    r"\b(full[- ]time|part[- ]time|contract|freelance|temporary|temp|"
    r"fixed[- ]term|internship|intern|learnership|graduate|volunteer)\b",
    re.I,
)


def _join_split_dates(text: str) -> str:
    """
    Join date ranges that have been split across lines by multi-column extraction.
    e.g. "01-2024 -\nDec 2024" -> "01-2024 - Dec 2024"
         "02/01/2023\n- 1st of\nDecember\n2023" -> "02/01/2023 - 1st of December 2023"
    """
    # Join a trailing dash/dash+newline with the next line
    text = re.sub(r"(\d{4})\s*[-–]\s*\n\s*([A-Za-z])", r"\1 - \2", text)
    text = re.sub(r"(\d{1,2}/\d{4})\s*\n\s*[-–]\s*", r"\1 - ", text)
    # Collapse "Month\nYear" continuations (e.g., "December\n2023")
    text = re.sub(r"(January|February|March|April|May|June|July|August|"
                  r"September|October|November|December)\s*\n\s*(\d{4})", r"\1 \2", text)
    # "1st of\nDecember" -> "1st of December"
    text = re.sub(r"(\d+(?:st|nd|rd|th)?\s+of)\s*\n\s*", r"\1 ", text)
    return text


def _extract_work_experiences(sections: dict, text: str) -> list[dict]:
    """
    Extract work experience entries. Uses the EXPERIENCE section text first,
    then falls back to scanning the full text for date ranges.
    """
    section_text = ""
    for key in ("WORK EXPERIENCE", "PROFESSIONAL EXPERIENCE", "EMPLOYMENT HISTORY",
                "CAREER HISTORY", "EXPERIENCE"):
        if key in sections and sections[key]:
            section_text = sections[key]
            break

    # Pre-process: join split date ranges produced by column extraction
    search_text = _join_split_dates(section_text or text)
    entries: list[dict] = []
    seen_ranges: set[tuple] = set()

    # Collect all date ranges in the section text
    all_date_matches = list(_DATE_RANGE_RE.finditer(search_text))

    # Also find job entries WITHOUT dates (for orphaned-date pairing)
    # These appear as company/title lines NOT adjacent to a date range
    date_positions = {dm.start() for dm in all_date_matches}

    for dm in all_date_matches:
        start_raw, end_raw = dm.group(1), dm.group(2)
        start_str = _parse_date(start_raw)
        is_cur = _is_present(end_raw)
        end_str = None if is_cur else _parse_date(end_raw)

        key = (start_str, end_str)
        if key in seen_ranges:
            continue
        seen_ranges.add(key)

        # Context before and after the date range
        pre_lines = [l.strip() for l in search_text[:dm.start()].splitlines() if l.strip()][-8:]
        post_lines = [l.strip() for l in search_text[dm.end():].splitlines() if l.strip()][:12]

        job_title = company = location = emp_type = ""
        desc_lines: list[str] = []

        # Try to find job title and company from lines near the date
        for line in reversed(pre_lines):
            lc = _clean(line)
            if not lc or _DATE_RANGE_RE.search(lc):
                continue
            # Split "Title at Company" or "Title, Company"
            sep = re.split(r"\s+(?:at|@|–|-)\s+|\s*,\s*(?=[A-Z])", lc, maxsplit=1)
            if len(sep) == 2 and 3 < len(sep[0]) < 80 and 3 < len(sep[1]) < 100:
                job_title, company = _clean(sep[0]), _clean(sep[1])
            else:
                if not job_title:
                    job_title = lc
                elif not company:
                    company = lc
            if job_title and company:
                break

        # If still missing, scan post lines for company-like content
        if not company and post_lines:
            for line in post_lines[:3]:
                lc = _clean(line)
                if lc and not _DATE_RANGE_RE.search(lc) and lc != job_title:
                    if re.search(r"\b(university|college|pty|ltd|inc|pharmacare|department)\b", lc, re.I):
                        company = lc
                        break

        # Employment type
        ctx = " ".join(pre_lines + post_lines[:5])
        em = _EMP_TYPES.search(ctx)
        if em:
            emp_type = em.group(1).title()

        # Location
        for l in (pre_lines + post_lines)[:6]:
            if _SA_PLACES.search(l) and l != job_title and l != company:
                location = _clean(l)
                break

        # Description bullets
        for l in post_lines:
            stripped = l.lstrip("*•-–>◦▪▸ ")
            if stripped and len(stripped) > 10 and not _DATE_RANGE_RE.search(l):
                # Stop if we hit a new section header
                if re.match(r"^(EDUCATION|SKILLS|REFERENCE|OBJECTIVE|SUMMARY)", stripped, re.I):
                    break
                desc_lines.append(stripped)
            if len(desc_lines) >= 6:
                break

        if not job_title and not company:
            continue
        if re.search(r"\b(university|college|diploma|degree|certificate|school)\b", job_title, re.I):
            continue

        entries.append({
            "job_title": job_title[:150],
            "company": company[:150],
            "location": location[:100],
            "employment_type": emp_type,
            "start_date": start_str,
            "end_date": end_str,
            "is_current": is_cur,
            "description": _clean(" ".join(desc_lines))[:500],
        })

    # ── Orphaned-date recovery ─────────────────────────────────────────────────
    # Some layouts put ALL dates in a separate column; they end up clustered at
    # the bottom of the section after normal extraction. Match them to entries
    # by order if we found no dates near the job titles.
    if not entries and section_text:
        orphan_dates = list(_DATE_RANGE_RE.finditer(_join_split_dates(text)))
        # Find job/company lines by looking for lines that aren't dates/bullets
        job_lines = []
        for line in _lines(section_text):
            if (not _DATE_RANGE_RE.search(line)
                    and not line.startswith(("-", "•", "*"))
                    and len(line) > 5 and len(line) < 100):
                job_lines.append(line)

        # Pair dates with job lines by order
        for i, dm in enumerate(orphan_dates[:6]):
            start_raw, end_raw = dm.group(1), dm.group(2)
            start_str = _parse_date(start_raw)
            is_cur = _is_present(end_raw)
            end_str = None if is_cur else _parse_date(end_raw)
            if not start_str:
                continue
            # Try to guess job_title / company from job_lines
            base = i * 3  # crude: assume ~3 lines per entry
            job_title = job_lines[base] if base < len(job_lines) else ""
            company = job_lines[base + 1] if base + 1 < len(job_lines) else ""
            entries.append({
                "job_title": job_title[:150],
                "company": company[:150],
                "location": "",
                "employment_type": "",
                "start_date": start_str,
                "end_date": end_str,
                "is_current": is_cur,
                "description": "",
            })

    # Deduplicate
    seen: dict[tuple, dict] = {}
    for e in entries:
        k = (e["job_title"].lower()[:30], e["company"].lower()[:30])
        if k not in seen or len(e["description"]) > len(seen[k]["description"]):
            seen[k] = e
    return sorted(seen.values(), key=lambda x: x["start_date"] or "", reverse=True)[:12]


# ── Education ──────────────────────────────────────────────────────────────────

_NQF_MAP = {
    "10": ["phd", "doctoral", "doctorate", "d.phil"],
    "9": ["masters", "master of", "m.sc", "msc", "mba", "m.com", "mcom", "m.eng", "llm"],
    "8": ["honours", "hons", "postgraduate diploma", "pgdip"],
    "7": ["bachelor", "b.sc", "bsc", "b.com", "bcom", "b.tech", "btech", "b.eng", "beng", "llb", "degree"],
    "6": ["national diploma", "nd ", "diploma"],
    "5": ["higher certificate"],
    "4": ["matric", "grade 12", "national senior certificate", "nsc"],
}

_INST_RE = re.compile(
    r"\b(university|universiteit|college|institute|school|academy|"
    r"polytechnic|tvet|varsity|faculty|campus|seta)\b",
    re.I,
)

def _infer_nqf(qual: str) -> str:
    lc = qual.lower()
    for level, kws in _NQF_MAP.items():
        if any(kw in lc for kw in kws):
            return level
    return ""

def _extract_educations(sections: dict, text: str) -> list[dict]:
    section = ""
    for key in ("EDUCATION AND TRAINING", "EDUCATION & TRAINING", "ACADEMIC BACKGROUND",
                "ACADEMIC QUALIFICATIONS", "QUALIFICATIONS", "EDUCATION"):
        if key in sections and sections[key]:
            section = sections[key]
            break
    if not section:
        section = _get_section(text, "EDUCATION", "QUALIFICATIONS")
    if not section:
        return []

    _TABLE_HEADER = re.compile(r"^(course|degree|school|university|grade|score|year)\b", re.I)
    year_re = re.compile(r"\b((?:19|20)\d{2})\b")
    entries: list[dict] = []
    blocks = re.split(r"\n{2,}|\n(?=\s*(?:19|20)\d{2})", section.strip())

    for block in blocks:
        block = block.strip()
        if not block or len(block) < 8:
            continue
        raw_lines = [l.strip() for l in block.splitlines() if l.strip()]
        # Skip table header rows
        if raw_lines and _TABLE_HEADER.match(raw_lines[0]):
            continue
        qual = institution = field = description = ""
        start_year = end_year = 0
        is_current = False

        years = year_re.findall(block)

        if len(raw_lines) >= 2:
            # Check for table-style: "Qualification | Institution | Grade | Year"
            parts = [p.strip() for p in raw_lines[0].split("|")]
            if len(parts) >= 2:
                qual = _clean(parts[0])
                institution = _clean(parts[1]) if len(parts) > 1 else ""
                ym = year_re.search(parts[-1]) if parts else None
                if ym:
                    end_year = int(ym.group(1))
                    start_year = end_year - 1
            else:
                qual = _clean(raw_lines[0])
                # Second line: institution or year
                if _INST_RE.search(raw_lines[1]) or not year_re.search(raw_lines[1]):
                    institution = _clean(raw_lines[1])
                else:
                    start_year = int(years[0]) if years else 0
            description = _clean(" ".join(raw_lines[2:]))
        else:
            qual = _clean(raw_lines[0]) if raw_lines else ""

        if years and not end_year:
            start_year = int(years[0]) if years else 0
            end_year = int(years[-1]) if len(years) > 1 else start_year

        is_current = bool(re.search(r"present|current|ongoing|in progress", block, re.I))
        if is_current:
            end_year = 0

        if _INST_RE.search(qual) and not _INST_RE.search(institution):
            qual, institution = institution, qual

        nqf = _infer_nqf(qual) or _infer_nqf(institution)

        if not qual and not institution:
            continue
        entries.append({
            "institution": institution[:200],
            "qualification": qual[:200],
            "field_of_study": field[:150],
            "nqf_level": nqf,
            "start_year": start_year,
            "end_year": end_year if not is_current else None,
            "is_current": is_current,
            "description": description[:300],
        })
    return entries[:8]


# ── Skills ─────────────────────────────────────────────────────────────────────

_LEVEL_RE = re.compile(
    r"\b(expert|advanced|proficient|strong|solid|good|intermediate|"
    r"working knowledge|familiar|basic|beginner|entry[- ]level)\b",
    re.I,
)
_LEVEL_MAP = {
    "expert": "expert", "advanced": "advanced", "proficient": "advanced",
    "strong": "advanced", "solid": "advanced", "good": "intermediate",
    "intermediate": "intermediate", "working knowledge": "intermediate",
    "familiar": "intermediate", "basic": "beginner", "beginner": "beginner",
    "entry-level": "beginner", "entry level": "beginner",
}
_TECH_RE = re.compile(
    r"\b(python|java(?:script)?|typescript|c\+\+|c#|php|ruby|swift|kotlin|"
    r"go(?:lang)?|rust|scala|matlab|bash|shell|powershell|"
    r"html5?|css3?|react(?:\.js)?|vue(?:\.js)?|angular(?:js)?|next(?:\.js)?|"
    r"node(?:\.js)?|express(?:\.js)?|django|flask|fastapi|spring(?:\s+boot)?|"
    r"laravel|rails|asp\.net|\.net|"
    r"sql|mysql|postgresql|sqlite|mongodb|redis|elasticsearch|firebase|"
    r"aws|azure|gcp|google cloud|docker|kubernetes|terraform|ansible|jenkins|"
    r"git|linux|ubuntu|excel|word|powerpoint|office\s+365|google\s+workspace|"
    r"sap|erp|sage|xero|quickbooks|pastel|"
    r"illustrator|photoshop|figma|canva|autocad|solidworks|"
    r"machine\s+learning|deep\s+learning|tensorflow|pytorch|scikit|keras|"
    r"pandas|numpy|matplotlib|power\s+bi|tableau|"
    r"spectroscopy|nmr|ftir|uv.vis|mass\s+spectrometry|"
    r"distillation|crystallization|titration|chromatography|hplc|gcms)\b",
    re.I,
)


def _extract_skills(sections: dict, text: str) -> list[dict]:
    section = ""
    for key in ("TECHNICAL SKILLS", "CORE COMPETENCIES", "KEY COMPETENCIES",
                "COMPUTER SKILLS", "IT SKILLS", "COMPETENCIES", "SKILLS", "PERSONAL SKILLS"):
        if key in sections and sections[key]:
            section = sections[key]
            break
    if not section:
        section = _get_section(text, "SKILLS", "COMPETENCIES")

    source = section or text
    found: dict[str, dict] = {}

    # Tech skills from regex
    for m in _TECH_RE.finditer(source):
        name = _clean(m.group())
        ctx = source[max(0, m.start() - 40):m.end() + 40]
        lm = _LEVEL_RE.search(ctx)
        level = _LEVEL_MAP.get((lm.group(1).lower() if lm else "").replace("-", " "), "intermediate")
        key = name.lower()
        if key not in found:
            found[key] = {"name": name.title(), "level": level, "category": "Technical"}

    # Plain skill items from section
    if section:
        plain = _TECH_RE.sub("", section)
        for item in re.split(r"[,•|\n/;]+", plain):
            item = _clean(item.lstrip("*•-–> "))
            # Skip percentage lines (skill bars), short noise, years
            if 2 < len(item) < 70 and not re.search(r"\d{2,}%|\d{4}", item):
                lm = _LEVEL_RE.search(item)
                level = _LEVEL_MAP.get((lm.group(1).lower() if lm else "").replace("-", " "), "intermediate")
                clean_name = _LEVEL_RE.sub("", item).strip(" ()")
                k = clean_name.lower()
                if k and k not in found and len(k) > 2:
                    found[k] = {"name": clean_name.title(), "level": level, "category": ""}

    return list(found.values())[:35]


# ── Languages ──────────────────────────────────────────────────────────────────

_LANG_LIST = [
    "english", "afrikaans", "zulu", "isizulu", "xhosa", "isixhosa", "sotho", "sesotho",
    "tswana", "setswana", "venda", "tshivenda", "tsonga", "xitsonga", "swati", "siswati",
    "ndebele", "isindebele", "pedi", "sepedi", "french", "spanish", "portuguese",
    "mandarin", "cantonese", "arabic", "hindi", "urdu", "german", "italian", "dutch",
    "russian", "japanese", "korean",
]
_PROF_MAP = {
    "native": "native", "mother tongue": "native", "home language": "native",
    "fluent": "native", "bilingual": "native", "first language": "native",
    "professional": "professional", "business": "professional", "advanced": "professional",
    "conversational": "conversational", "intermediate": "conversational",
    "working": "conversational", "basic": "basic", "elementary": "basic",
}
_LANG_RE = re.compile(
    r"\b(" + "|".join(re.escape(l) for l in _LANG_LIST) + r")\b"
    r"(?:\s*[-:–(]+\s*([A-Za-z\s]+?)(?:[,;\n)]|$)|\s*\(([^)]+)\))?",
    re.I,
)

def _extract_languages(sections: dict, text: str) -> list[dict]:
    found: dict[str, dict] = {}

    section = sections.get("LANGUAGE PROFICIENCY") or sections.get("LANGUAGES SPOKEN") or sections.get("LANGUAGES", "")
    if section and not re.search(r"(design|system|research|symbolic|writing)", section, re.I):
        for line in _lines(section):
            m = re.match(r"([A-Za-z]{3,})\s*[-:–(]+\s*([A-Za-z\s]+)", line)
            if m and m.group(1).lower() in _LANG_LIST:
                lang, raw = m.group(1).title(), m.group(2).lower()
                prof = next((v for k, v in _PROF_MAP.items() if k in raw), "professional")
                found[lang.lower()] = {"name": lang, "proficiency": prof}

    if not found:
        for m in _LANG_RE.finditer(text[:3000]):
            lang = m.group(1).title()
            raw_prof = (m.group(2) or m.group(3) or "").strip().lower()
            prof = next((v for k, v in _PROF_MAP.items() if k in raw_prof), "professional")
            found[lang.lower()] = {"name": lang, "proficiency": prof}

    return list(found.values())[:12]


# ── References ─────────────────────────────────────────────────────────────────

def _extract_references(sections: dict, text: str) -> list[dict]:
    section = ""
    for key in ("PROFESSIONAL REFERENCES", "CHARACTER REFERENCES", "REFERENCES", "REFERENCE"):
        if key in sections and sections[key]:
            section = sections[key]
            break
    if not section:
        section = _get_section(text, "REFERENCES", "REFERENCE")
    if not section or re.search(r"available\s+(?:on|upon)\s+request", section, re.I):
        return []

    # Split into ref blocks
    blocks = re.split(r"\n{2,}", section.strip())
    if len(blocks) <= 1:
        blocks = re.split(r"(?=\b(?:Mr|Mrs|Ms|Dr|Prof)\b)", section)

    entries: list[dict] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        raw_lines = [l.strip() for l in block.splitlines() if l.strip()]
        name = position = company = phone = email = ""

        for line in raw_lines:
            if not name:
                # First substantial line is the name
                if re.match(r"\b(Mr|Mrs|Ms|Dr|Prof)\b", line) or (
                    _NAME_RE.match(line) and not _EMAIL_RE.search(line) and not _PHONE_RE.search(line)
                ):
                    # Strip "Name - Company" pattern
                    dash_split = re.split(r"\s*[-–]\s*", line, maxsplit=1)
                    name = _clean(dash_split[0])
                    if len(dash_split) > 1:
                        company = _clean(dash_split[1])
                    continue
            if _EMAIL_RE.search(line):
                email = _EMAIL_RE.search(line).group()
            elif _PHONE_RE.search(line):
                phone = _PHONE_RE.search(line).group()
            elif not position and not _INST_RE.search(line.lower()[:3]):
                position = _clean(line)
            elif not company:
                company = _clean(line)

        if not name:
            continue
        entries.append({
            "name": name[:150], "position": position[:150], "company": company[:150],
            "relationship": "", "email": email, "phone": phone,
        })
    return entries[:5]


# ── Years Experience ───────────────────────────────────────────────────────────

def _infer_years_experience(text: str, work_experiences: list[dict]) -> str:
    m = re.search(r"\b(\d+)\+?\s*years?\s+(?:of\s+)?(?:work\s+)?experience", text, re.I)
    if m:
        n = int(m.group(1))
        if n < 1: return "0-1"
        if n <= 2: return "1-2"
        if n <= 5: return "3-5"
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
        if span < 1: return "0-1"
        if span <= 2: return "1-2"
        if span <= 5: return "3-5"
        if span <= 10: return "5-10"
        return "10+"
    return ""


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_cv(file_bytes: bytes, mime_type: str = "application/pdf") -> dict[str, Any]:
    if "pdf" in mime_type:
        text = extract_text_layout_aware(file_bytes)
        header_text = extract_header_area(file_bytes)
    elif "image" in mime_type:
        return _empty()
    else:
        text = extract_text_from_docx(file_bytes)
        header_text = ""

    if not text.strip():
        return _empty()

    text = _norm(text)
    text = _join_split_dates(text)
    header_text = _norm(header_text)
    lines = _lines(text)
    header_lines = _lines(header_text) if header_text else lines

    # Build section map once — used by all extractors
    sections = _find_sections(text)

    email = _extract_email(text, header_text)
    phone = _extract_phone(text, header_text)
    # Use header area for name (avoids picking up sidebar skill/job-title words)
    first, last = _extract_name(header_lines)
    if not first:
        first, last = _extract_name(lines)
    location = _extract_location(header_lines or lines, text)
    linkedin = _extract_linkedin(text)
    github = _extract_github(text)
    portfolio = _extract_portfolio(text)
    bio = _extract_bio(sections, text)
    occupation = _extract_occupation(lines, f"{first} {last}")
    experiences = _extract_work_experiences(sections, text)
    educations = _extract_educations(sections, text)
    skills = _extract_skills(sections, text)
    languages = _extract_languages(sections, text)
    references = _extract_references(sections, text)
    years_exp = _infer_years_experience(text, experiences)

    return {
        "first_name": first, "last_name": last, "phone": phone, "location": location,
        "occupation": occupation, "years_experience": years_exp, "bio": bio,
        "linkedin_url": linkedin, "github_url": github, "portfolio_url": portfolio,
        "work_experiences": experiences, "educations": educations, "skills": skills,
        "languages": languages, "references": references,
    }


def _empty() -> dict[str, Any]:
    return {
        "first_name": "", "last_name": "", "phone": "", "location": "",
        "occupation": "", "years_experience": "", "bio": "",
        "linkedin_url": "", "github_url": "", "portfolio_url": "",
        "work_experiences": [], "educations": [], "skills": [],
        "languages": [], "references": [],
    }
