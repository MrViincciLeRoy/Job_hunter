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


def _blocks_in_band(blocks: list[dict], x_left: float, x_right: float) -> list[dict]:
    return [b for b in blocks if x_left <= b["x0"] < x_right]


def _column_text(blocks: list[dict]) -> str:
    sorted_blocks = sorted(blocks, key=lambda b: (round(b["y0"] / 4) * 4, b["x0"]))
    return "\n".join(b["text"] for b in sorted_blocks)


def _detect_columns(blocks: list[dict], page_width: float) -> list[float]:
    if not blocks:
        return [0, page_width]
    x_starts = sorted({round(b["x0"] / 5) * 5 for b in blocks})
    gaps = []
    for i in range(1, len(x_starts)):
        gap = x_starts[i] - x_starts[i - 1]
        if gap > 30:
            gaps.append((gap, (x_starts[i - 1] + x_starts[i]) / 2))
    if not gaps:
        return [0, page_width]
    gaps.sort(reverse=True)
    splits = sorted(mid for _, mid in gaps[:2])
    return [0] + splits + [page_width]


def _strip_icon_prefix(text: str) -> str:
    """Strip leading non-ASCII icon/symbol characters (common in icon-font PDF bullets)."""
    return re.sub(r'^[\x80-\xff\u0080-\uffff]+', '', text).strip()


_SECTION_LABEL_RE = re.compile(
    r'^(OBJECTIVE|EXPERIENCE|EDUCATION|SKILLS|REFERENCE|REFERENCES|CONTACT|'
    r'SUMMARY|PROFILE|ABOUT|WORK\s+EXPERIENCE|PROFESSIONAL\s+EXPERIENCE|'
    r'EMPLOYMENT|QUALIFICATIONS|CERTIFICATIONS|LANGUAGES|ACHIEVEMENTS|'
    r'Objective|Experience|Education|Skills|Reference|References|Contact|'
    r'Summary|Profile|About)$'
)


def _is_section_label(text: str) -> bool:
    """Match section label after stripping leading icon-font characters."""
    clean = _strip_icon_prefix(text.strip().split('\n')[0].strip())
    return bool(_SECTION_LABEL_RE.match(clean))


def _section_label_text(text: str) -> str:
    """Return the clean section label string (uppercase), or empty string."""
    clean = _strip_icon_prefix(text.strip().split('\n')[0].strip())
    m = _SECTION_LABEL_RE.match(clean)
    return m.group(1).upper() if m else ""


def _classify_layout(blocks: list[dict], page_width: float) -> str:
    """
    Classify the PDF page layout into one of:
      'dates_right'     — dates float to far-right (x > 60% page), content left
      'dates_left'      — dates in narrow left col, content in right col (name far right)
      'dates_sidebar'   — sidebar col (x<100) has section labels + dates; content at x>150
      'three_column'    — 3 distinct x-columns (left sidebar, mid-dates, right content)
      'standard'        — normal; handle with default column detection

    FIX LOG:
      - Strip icon-prefix chars before section label matching (fixes CV with icon bullets)
      - dates_sidebar requires meaningful right-col content (fixes single-col false trigger)
      - three_column detection moved before dates_right to catch icon-label CVs
    """
    date_re = re.compile(
        r'\b(?:\d{1,2}[-/]\d{4})\b'
        r'|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4}\b'
        r'|\b\d{4}\s*[-–]\s*(?:\d{4}|present|current)\b', re.I
    )

    date_blocks  = [b for b in blocks if date_re.search(b["text"]) and len(b["text"]) < 90]
    section_blocks = [b for b in blocks if _is_section_label(b["text"])]

    if not date_blocks:
        return 'standard'

    date_xs = [b["x0"] for b in date_blocks]
    avg_date_x = sum(date_xs) / len(date_xs)

    section_xs = [b["x0"] for b in section_blocks]
    avg_section_x = sum(section_xs) / len(section_xs) if section_xs else page_width / 2

    # --- THREE_COLUMN: check early so icon-label CVs don't fall through to dates_right ---
    # Typical: left (x<~150) = sidebar labels/contact, mid (x=~200-450) = dates+content,
    # right (x>~450) = date fragments OR additional content
    # FIX: When >3 column boundaries exist, try all consecutive pairs as the left/right split
    # to handle cases where PDF renders with 4 distinct x-clusters (e.g. icon-font sidebar CVs).
    distinct_xs = sorted(set(round(b["x0"] / 15) * 15 for b in blocks))
    col_boundaries = [0]
    for i in range(1, len(distinct_xs)):
        if distinct_xs[i] - distinct_xs[i-1] > 80:
            col_boundaries.append((distinct_xs[i-1] + distinct_xs[i]) / 2)

    # Try all possible (left_split, right_split) pairs from col_boundaries
    found_three_col = False
    if len(col_boundaries) >= 3:
        for li in range(1, len(col_boundaries)):
            for ri in range(li + 1, len(col_boundaries) + 1):
                left_x = col_boundaries[li - 1] if li > 0 else 0
                mid_x_min = col_boundaries[li]
                mid_x_max = col_boundaries[ri] if ri < len(col_boundaries) else page_width

                mid_date_blocks = [b for b in date_blocks if mid_x_min <= b["x0"] < mid_x_max]
                right_content_blocks = [b for b in blocks if b["x0"] >= mid_x_max and len(b["text"]) > 20]
                right_date_blocks = [b for b in date_blocks if b["x0"] >= mid_x_max]
                mid_content_blocks = [b for b in blocks if mid_x_min <= b["x0"] < mid_x_max and len(b["text"]) > 20]
                left_blocks_check = [b for b in blocks if b["x0"] < mid_x_min]

                if (len(mid_date_blocks) >= 1 and len(right_content_blocks) >= 3) or \
                   (len(right_date_blocks) >= 1 and len(mid_content_blocks) >= 3 and
                    len(left_blocks_check) >= 3):
                    found_three_col = True
                    break
            if found_three_col:
                break
    if found_three_col:
        return 'three_column'

    # --- DATES_RIGHT: all date blocks are in the far right zone (> 55% of page width)
    if avg_date_x > page_width * 0.55 and avg_section_x < page_width * 0.55:
        return 'dates_right'

    # --- DATES_LEFT: dates in narrow left column, name far right ---
    left_dates = [b for b in date_blocks if b["x0"] < 80]
    right_content = [b for b in blocks if b["x0"] > 140 and len(b["text"]) > 20]
    name_far_right = any(b["x0"] > page_width * 0.60 for b in blocks
                         if not _is_section_label(b["text"])
                         and len(b["text"]) < 60 and b["y0"] < 100)
    if len(left_dates) >= 2 and len(right_content) >= 4 and name_far_right:
        return 'dates_left'

    # --- DATES_SIDEBAR: section headers at x<80 AND dates at x<80, content at x>100
    # FIX: Require meaningful content in right column (prevents false trigger on single-col PDFs)
    sidebar_section = [b for b in section_blocks if b["x0"] < 80]
    sidebar_dates = [b for b in date_blocks if b["x0"] < 80]
    right_col_content = [b for b in blocks if b["x0"] >= 100]
    if len(sidebar_section) >= 3 and len(sidebar_dates) >= 1 and len(right_col_content) >= 4:
        return 'dates_sidebar'

    return 'standard'


def _merge_adjacent_date_blocks(blocks: list[dict]) -> list[dict]:
    """
    Merge date/range fragments that were split into separate blocks
    (e.g., "01-2024 -" on one block and "Dec 2024" on the next).
    """
    date_frag_re = re.compile(
        r'^(?:\d{1,2}[-/]\d{4}|\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*'
        r'|\d+(?:st|nd|rd|th)?\s*(?:of)?|[-–]\s*\d|\d+|Present|Current|of)[\s\-]*$', re.I
    )
    result = []
    used = set()
    sorted_b = sorted(blocks, key=lambda b: (round(b["y0"] / 3) * 3, b["x0"]))

    for i, b in enumerate(sorted_b):
        if i in used:
            continue
        text = b["text"].strip()
        if not date_frag_re.match(text):
            result.append(b)
            continue
        merged_text = text
        merged_y1 = b["y1"]
        used.add(i)
        for j in range(i + 1, min(i + 6, len(sorted_b))):
            if j in used:
                continue
            nb = sorted_b[j]
            if abs(nb["x0"] - b["x0"]) > 30:
                continue
            if nb["y0"] > merged_y1 + 30:
                break
            nt = nb["text"].strip()
            merged_text = (merged_text + " " + nt).strip()
            merged_y1 = nb["y1"]
            used.add(j)
        result.append({**b, "text": merged_text, "y1": merged_y1})

    return result


def _reconstruct_dates_left(blocks: list[dict]) -> str:
    """
    Layout: narrow left column has dates (x<80), wide right column has
    section headers + content (x>140).
    """
    left_blocks = sorted([b for b in blocks if b["x0"] < 100], key=lambda b: b["y0"])
    right_blocks = sorted([b for b in blocks if b["x0"] >= 100], key=lambda b: b["y0"])

    left_blocks = _merge_adjacent_date_blocks(left_blocks)

    date_annotations: dict[int, str] = {}
    for lb in left_blocks:
        best_rb, best_dy = None, float('inf')
        for rb in right_blocks:
            dy = abs(rb["y0"] - lb["y0"])
            if dy < best_dy:
                best_dy, best_rb = dy, rb
        if best_rb is not None and best_dy < 80:
            existing = date_annotations.get(id(best_rb), "")
            lt = lb["text"].strip()
            date_annotations[id(best_rb)] = (existing + " " + lt).strip() if existing else lt

    lines = []
    for rb in right_blocks:
        text = rb["text"].strip()
        date = date_annotations.get(id(rb), "")
        lines.append(f"{text}  {date}" if date else text)
    return "\n".join(lines)


def _reconstruct_dates_sidebar(blocks: list[dict]) -> str:
    """
    Layout: left sidebar (x<80) has BOTH section labels AND dates.
    Right column (x>150) has all content without section boundaries.
    """
    sidebar = sorted([b for b in blocks if b["x0"] < 100], key=lambda b: b["y0"])
    content = sorted([b for b in blocks if b["x0"] >= 100], key=lambda b: b["y0"])

    content = _merge_adjacent_date_blocks(content)

    sections_y: list[tuple[str, float]] = []
    for b in sidebar:
        label = _section_label_text(b["text"])
        if label:
            sections_y.append((label, b["y0"]))

    date_re = re.compile(r'\b(?:\d{1,2}[-/]\d{4}|\d{4})\b', re.I)
    sidebar_dates = [b for b in sidebar if date_re.search(b["text"]) and
                     not _is_section_label(b["text"])]
    sidebar_dates = _merge_adjacent_date_blocks(sidebar_dates)

    date_annotations: dict[int, str] = {}
    for db in sidebar_dates:
        best_cb, best_dy = None, float('inf')
        for cb in content:
            dy = abs(cb["y0"] - db["y0"])
            if dy < best_dy:
                best_dy, best_cb = dy, cb
        if best_cb is not None and best_dy < 60:
            existing = date_annotations.get(id(best_cb), "")
            dt = db["text"].strip()
            date_annotations[id(best_cb)] = (existing + " " + dt).strip() if existing else dt

    if not sections_y:
        lines = []
        for cb in content:
            text = cb["text"].strip()
            date = date_annotations.get(id(cb), "")
            lines.append(f"{text}  {date}" if date else text)
        return "\n".join(lines)

    result_parts = []
    first_y = sections_y[0][1]
    header_blocks = [b for b in content if b["y0"] < first_y - 10]
    if header_blocks:
        hlines = []
        for b in header_blocks:
            text = b["text"].strip()
            date = date_annotations.get(id(b), "")
            hlines.append(f"{text}  {date}" if date else text)
        result_parts.append("\n".join(hlines))

    for i, (label, y_start) in enumerate(sections_y):
        y_end = sections_y[i + 1][1] if i + 1 < len(sections_y) else float('inf')
        section_blocks = [b for b in content if y_start - 25 <= b["y0"] < y_end]
        lines = []
        for b in section_blocks:
            text = b["text"].strip()
            date = date_annotations.get(id(b), "")
            lines.append(f"{text}  {date}" if date else text)
        result_parts.append(f"{label}\n" + "\n".join(lines))

    return "\n\n".join(result_parts)


def _reconstruct_dates_right(blocks: list[dict], page_width: float) -> str:
    """
    Layout: content in left column, dates floated to far right.

    FIX: Only annotate right-side blocks that actually contain date strings.
    Previously ALL right-side blocks (including name/contact) were used as
    date annotations, causing garbled output like "Objective  Ronda Chauke 11th St".
    Also tightened y-proximity threshold from 100px to 60px.
    """
    all_x0s = sorted(set(round(b["x0"] / 5) * 5 for b in blocks))
    split_x = page_width * 0.55
    for i in range(1, len(all_x0s)):
        if all_x0s[i] - all_x0s[i-1] > 50:
            split_x = (all_x0s[i-1] + all_x0s[i]) / 2
            break

    left_blocks = sorted([b for b in blocks if b["x0"] <= split_x], key=lambda b: b["y0"])
    right_blocks = sorted([b for b in blocks if b["x0"] > split_x], key=lambda b: b["y0"])

    right_blocks = _merge_adjacent_date_blocks(right_blocks)

    # FIX: Only use right-side blocks that actually contain a date pattern
    date_re = re.compile(
        r'\b(?:\d{1,2}[-/]\d{4}|\d{4}[-–]\d{4}|\d{4})\b'
        r'|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4}\b',
        re.I
    )
    right_date_blocks = [b for b in right_blocks if date_re.search(b["text"])]

    date_annotations: dict[int, str] = {}
    for rb in right_date_blocks:
        best_lb, best_dy = None, float('inf')
        for lb in left_blocks:
            dy = abs(lb["y0"] - rb["y0"])
            if dy < best_dy:
                best_dy, best_lb = dy, lb
        # FIX: tightened from 100px to 60px
        if best_lb is not None and best_dy < 60:
            existing = date_annotations.get(id(best_lb), "")
            rt = rb["text"].strip()
            date_annotations[id(best_lb)] = (existing + " " + rt).strip() if existing else rt

    lines = []
    for lb in left_blocks:
        text = lb["text"].strip()
        date = date_annotations.get(id(lb), "")
        lines.append(f"{text}  {date}" if date else text)
    return "\n".join(lines)


def _reconstruct_two_col_sidebar(blocks: list[dict]) -> str:
    """
    Layout: narrow left sidebar has section headers, right column has
    all content + dates.
    """
    sidebar_x_thresh = 100
    sidebar = sorted([b for b in blocks if b["x0"] < sidebar_x_thresh], key=lambda b: b["y0"])
    content = sorted([b for b in blocks if b["x0"] >= sidebar_x_thresh], key=lambda b: b["y0"])

    sections_y: list[tuple[str, float]] = []
    for b in sidebar:
        label = _section_label_text(b["text"])
        if label:
            sections_y.append((label, b["y0"]))

    if not sections_y:
        return _column_text(blocks)

    result_parts = []
    first_y = sections_y[0][1]
    header_blocks = [b for b in content if b["y0"] < first_y - 10]
    if header_blocks:
        result_parts.append(_column_text(header_blocks))

    for i, (label, y_start) in enumerate(sections_y):
        y_end = sections_y[i + 1][1] if i + 1 < len(sections_y) else float('inf')
        section_blocks = [b for b in content if y_start - 25 <= b["y0"] < y_end]
        section_text = _column_text(section_blocks)
        result_parts.append(f"{label}\n{section_text}")

    return "\n\n".join(result_parts)


def _reconstruct_three_column(blocks: list[dict], page_width: float) -> str:
    """
    Layout: left sidebar (contact/skills/refs), mid column (content + possibly dates),
    right column (date fragments OR section headers + content).

    FIX: Handles two sub-cases:
      A) Mid col has dates, right col has section+content (original behavior)
      B) Right col has date fragments, mid col has section+content, left=sidebar
         (new case for icon-label CVs like CV_101755)
    """
    all_x0s = sorted(b["x0"] for b in blocks)
    gaps = []
    prev = all_x0s[0]
    for x in all_x0s[1:]:
        if x - prev > 40:
            gaps.append(((prev + x) / 2, x - prev))
        prev = x
    gaps.sort(key=lambda g: g[1], reverse=True)
    split_xs = sorted(g[0] for g in gaps[:2]) if len(gaps) >= 2 else [page_width * 0.35, page_width * 0.65]

    left_col = sorted([b for b in blocks if b["x0"] < split_xs[0]], key=lambda b: b["y0"])
    mid_col = sorted([b for b in blocks if split_xs[0] <= b["x0"] < split_xs[1]], key=lambda b: b["y0"])
    right_col = sorted([b for b in blocks if b["x0"] >= split_xs[1]], key=lambda b: b["y0"])

    date_re = re.compile(
        r'\b(?:\d{1,2}[-/]\d{4}|\d{4}[-–]\d{4})\b'
        r'|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4}\b', re.I
    )

    mid_has_dates = any(date_re.search(b["text"]) for b in mid_col)
    right_has_dates = any(date_re.search(b["text"]) for b in right_col)
    right_has_content = any(len(b["text"]) > 20 for b in right_col)

    if right_has_dates and not right_has_content:
        # Case B: dates are right-col fragments, content is mid-col
        mid_col = _merge_adjacent_date_blocks(mid_col)
        right_col_merged = _merge_adjacent_date_blocks(right_col)

        date_annotations: dict[int, str] = {}
        for rb in right_col_merged:
            if not date_re.search(rb["text"]):
                continue
            best_mb, best_dy = None, float('inf')
            for mb in mid_col:
                dy = abs(mb["y0"] - rb["y0"])
                if dy < best_dy:
                    best_dy, best_mb = dy, mb
            if best_mb is not None and best_dy < 80:
                existing = date_annotations.get(id(best_mb), "")
                rt = rb["text"].strip()
                date_annotations[id(best_mb)] = (existing + " " + rt).strip() if existing else rt

        # Build mid-col section-aware output
        sections_y: list[tuple[str, float]] = []
        for b in mid_col:
            label = _section_label_text(b["text"])
            if label:
                sections_y.append((label, b["y0"]))

        mid_lines = []
        for mb in mid_col:
            text = _strip_icon_prefix(mb["text"].strip())
            date = date_annotations.get(id(mb), "")
            mid_lines.append(f"{text}  {date}" if date else text)

        left_lines = []
        for lb in left_col:
            text = _strip_icon_prefix(lb["text"].strip())
            left_lines.append(text)

        return "\n".join(mid_lines) + "\n\n" + "\n".join(left_lines)

    else:
        # Case A: original behavior — mid col has dates, right col has content
        mid_col = _merge_adjacent_date_blocks(mid_col)

        date_annotations: dict[int, str] = {}
        for mb in mid_col:
            best_rb, best_dy = None, float('inf')
            for rb in right_col:
                dy = abs(rb["y0"] - mb["y0"])
                if dy < best_dy:
                    best_dy, best_rb = dy, rb
            if best_rb is not None and best_dy < 80:
                existing = date_annotations.get(id(best_rb), "")
                mt = mb["text"].strip()
                date_annotations[id(best_rb)] = (existing + " " + mt).strip() if existing else mt

        right_lines = []
        for rb in right_col:
            text = rb["text"].strip()
            date = date_annotations.get(id(rb), "")
            right_lines.append(f"{text}  {date}" if date else text)

        left_text = _column_text(left_col)
        right_text = "\n".join(right_lines)
        return right_text + "\n\n" + left_text


def _col_char_count(blocks: list[dict]) -> int:
    return sum(len(b["text"]) for b in blocks)


def extract_text_layout_aware(file_bytes: bytes) -> str:
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        all_pages: list[str] = []

        for page in doc:
            blocks = _extract_blocks(page)
            if not blocks:
                continue
            page_width = page.rect.width

            layout = _classify_layout(blocks, page_width)

            if layout == 'dates_right':
                all_pages.append(_reconstruct_dates_right(blocks, page_width))
            elif layout == 'dates_left':
                all_pages.append(_reconstruct_dates_left(blocks))
            elif layout == 'dates_sidebar':
                all_pages.append(_reconstruct_dates_sidebar(blocks))
            elif layout == 'three_column':
                all_pages.append(_reconstruct_three_column(blocks, page_width))
            else:
                # Standard: try column detection
                col_bounds = _detect_columns(blocks, page_width)
                if len(col_bounds) > 2:
                    col_bands = []
                    for i in range(len(col_bounds) - 1):
                        band = _blocks_in_band(blocks, col_bounds[i], col_bounds[i + 1])
                        ct = _column_text(band).strip()
                        if ct:
                            col_bands.append((band, ct))

                    # FIX: Reject false multi-column splits where one col has <10% of chars.
                    # This handles centered/single-column CVs that get split by narrow x-gaps
                    # from text wrapping (e.g. CV_135540 "Results-driven..." wraps to x0=31).
                    if col_bands:
                        total_chars = sum(_col_char_count(b) for b, _ in col_bands)
                        valid_bands = [(b, t) for b, t in col_bands
                                       if total_chars == 0 or _col_char_count(b) / total_chars > 0.10]
                        if len(valid_bands) >= 2 and all(len(t) > 20 for _, t in valid_bands):
                            all_pages.append("\n\n".join(t for _, t in valid_bands))
                            continue

                all_pages.append(_column_text(blocks))

        return "\n\n--- PAGE BREAK ---\n\n".join(all_pages)

    except ImportError:
        pass

    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            return "\n".join(p.extract_text(x_tolerance=2, y_tolerance=3) or "" for p in pdf.pages)
    except Exception:
        pass

    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception:
        pass

    return ""


def extract_header_area(file_bytes: bytes) -> str:
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
    "CERTIFICATES", "ACHIEVEMENTS", "AWARDS", "PROJECTS",
    "VOLUNTEER", "INTERESTS", "HOBBIES", "PERSONAL DETAILS",
    "PERSONAL INFORMATION", "CONTACT DETAILS", "CONTACT", "PERSONAL SKILLS",
    "REFERENCE",
]

def _find_sections(text: str) -> dict[str, str]:
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


def _get_section(text: str, *names: str) -> str:
    pat = re.compile(
        r"(?:^|\n)\s*(?:" + "|".join(re.escape(n) for n in names) + r")\s*[:\-]?\s*\n"
        r"([\s\S]*?)"
        r"(?=\n\s*(?:" + "|".join(re.escape(h) for h in _ALL_HEADERS) + r")\s*[:\-]?\s*\n|\n---\n|$)",
        re.I,
    )
    m = pat.search(text)
    return m.group(1).strip() if m else ""


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
    if header:
        m = _EMAIL_RE.search(header)
        if m:
            return m.group()
    ref_pos = re.search(r"\b(REFERENCE|REFERENCES)\b", text, re.I)
    search_text = text[:ref_pos.start()] if ref_pos else text
    m = _EMAIL_RE.search(search_text)
    return m.group() if m else (_EMAIL_RE.search(text).group() if _EMAIL_RE.search(text) else "")


def _extract_phone(text: str, header: str = "") -> str:
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
_NAME_PART_RE = re.compile(r"^[A-Z]{2,20}$")

_SKIP_HEADER = re.compile(
    r"\b(objective|experience|education|skills|reference|contact|"
    r"summary|profile|about|cv|resume|curriculum|personal|details|"
    r"analysis|interpretation|writing|reporting|solving|thinking|"
    r"collaboration|management|intern|assistant|manager|director|"
    r"lecturer|researcher|supervisor)\b", re.I
)


def _extract_name(lines: list[str]) -> tuple[str, str]:
    for line in lines[:35]:
        line = _clean(_strip_icon_prefix(line))
        if not line or "@" in line or len(line) > 65:
            continue
        if re.search(r"\d", line) or _SKIP_HEADER.search(line):
            continue
        if _NAME_RE.match(line) or _NAME_CAPS_RE.match(line):
            parts = line.title().split()
            if len(parts) >= 2:
                return parts[0], " ".join(parts[1:])

    for i in range(min(35, len(lines) - 1)):
        a, b = _clean(_strip_icon_prefix(lines[i])), _clean(_strip_icon_prefix(lines[i + 1]))
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

_EDU_LINE_RE = re.compile(
    r"\b(bachelor|honours|master|phd|diploma|degree|certificate|matric|"
    r"grade\s*12|bsc|b\.sc|msc|m\.sc|bcom|b\.com|university|college|institute|"
    r"faculty|distinctions?)\b",
    re.I,
)


def _is_likely_bullet(text: str) -> bool:
    if len(text) > 80:
        return True
    if re.match(r"^[-–*•]", text):
        return True
    if re.match(r"^(Performed|Conducted|Assisted|Maintained|Collaborated|Developed|"
                r"Managed|Implemented|Designed|Created|Led|Supported|Ensured)\b", text, re.I):
        return True
    return False


def _join_split_dates(text: str) -> str:
    text = re.sub(r"(\d{4})\s*[-–]\s*\n\s*([A-Za-z])", r"\1 - \2", text)
    text = re.sub(r"(\d{1,2}/\d{4})\s*\n\s*[-–]\s*", r"\1 - ", text)
    text = re.sub(r"(January|February|March|April|May|June|July|August|"
                  r"September|October|November|December)\s*\n\s*(\d{4})", r"\1 \2", text)
    text = re.sub(r"(\d+(?:st|nd|rd|th)?\s+of)\s*\n\s*", r"\1 ", text)
    return text


def _extract_work_experiences(sections: dict, text: str) -> list[dict]:
    section_text = ""
    for key in ("WORK EXPERIENCE", "PROFESSIONAL EXPERIENCE", "EMPLOYMENT HISTORY",
                "CAREER HISTORY", "EXPERIENCE"):
        if key in sections and sections[key]:
            section_text = sections[key]
            break

    search_text = _join_split_dates(section_text or text)
    entries: list[dict] = []
    seen_ranges: set[tuple] = set()
    all_date_matches = list(_DATE_RANGE_RE.finditer(search_text))

    for dm in all_date_matches:
        start_raw, end_raw = dm.group(1), dm.group(2)
        start_str = _parse_date(start_raw)
        is_cur = _is_present(end_raw)
        end_str = None if is_cur else _parse_date(end_raw)

        key = (start_str, end_str)
        if key in seen_ranges:
            continue
        seen_ranges.add(key)

        pre_lines = [l.strip() for l in search_text[:dm.start()].splitlines() if l.strip()][-8:]
        post_lines = [l.strip() for l in search_text[dm.end():].splitlines() if l.strip()][:12]

        job_title = company = location = emp_type = ""
        desc_lines: list[str] = []

        candidate_lines = []
        for line in reversed(pre_lines):
            lc = _clean(line)
            if not lc or _DATE_RANGE_RE.search(lc) or _EDU_LINE_RE.search(lc):
                continue
            if _is_likely_bullet(lc):
                continue
            candidate_lines.append(lc)
            if len(candidate_lines) >= 2:
                break

        if candidate_lines:
            job_title = candidate_lines[0]
            if len(candidate_lines) > 1:
                company = candidate_lines[1]

        if not job_title or not company:
            for line in post_lines[:4]:
                lc = _clean(line)
                if not lc or _DATE_RANGE_RE.search(lc) or _EDU_LINE_RE.search(lc):
                    continue
                if _is_likely_bullet(lc):
                    break
                if not job_title:
                    job_title = lc
                elif not company:
                    company = lc
                    break

        if job_title and not company:
            sep = re.split(r"\s*,\s*(?=[A-Z])|\s+(?:at|@)\s+", job_title, maxsplit=1)
            if len(sep) == 2 and 3 < len(sep[0]) < 80 and 3 < len(sep[1]) < 100:
                job_title, company = _clean(sep[0]), _clean(sep[1])

        ctx = " ".join(pre_lines[-3:] + post_lines[:5])
        em = _EMP_TYPES.search(ctx)
        if em:
            emp_type = em.group(1).title()

        for l in (pre_lines[-4:] + post_lines[:4]):
            if _SA_PLACES.search(l) and l != job_title and l != company:
                location = _clean(l)
                break

        in_desc = bool(company or job_title)
        skip_re = re.compile(
            r"^(EDUCATION|SKILLS|REFERENCE|OBJECTIVE|SUMMARY|PROFILE|CONTACT)", re.I
        )
        for l in post_lines:
            stripped = l.lstrip("*•-–>◦▪▸ ")
            if skip_re.match(stripped):
                break
            if _EDU_LINE_RE.search(stripped) and len(stripped) > 30:
                break
            if stripped and len(stripped) > 10 and not _DATE_RANGE_RE.search(l):
                if stripped != job_title and stripped != company:
                    desc_lines.append(stripped)
            if len(desc_lines) >= 6:
                break

        if _EDU_LINE_RE.search(job_title or ""):
            continue

        if not job_title and not company:
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

    if not entries and section_text:
        orphan_dates = list(_DATE_RANGE_RE.finditer(_join_split_dates(text)))
        job_lines = []
        for line in _lines(section_text):
            if (not _DATE_RANGE_RE.search(line)
                    and not line.startswith(("-", "•", "*"))
                    and not _EDU_LINE_RE.search(line)
                    and len(line) > 5 and len(line) < 100):
                job_lines.append(line)

        for i, dm in enumerate(orphan_dates[:6]):
            start_raw, end_raw = dm.group(1), dm.group(2)
            start_str = _parse_date(start_raw)
            is_cur = _is_present(end_raw)
            end_str = None if is_cur else _parse_date(end_raw)
            if not start_str:
                continue
            base = i * 3
            job_title = job_lines[base] if base < len(job_lines) else ""
            company = job_lines[base + 1] if base + 1 < len(job_lines) else ""
            if _EDU_LINE_RE.search(job_title):
                continue
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

_TABLE_HEADER_RE = re.compile(
    r"^(course|degree|school|university|grade|score|year)\b", re.I
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

    year_re = re.compile(r"\b((?:19|20)\d{2})\b")
    entries: list[dict] = []
    blocks = re.split(r"\n{2,}|\n(?=\s*(?:19|20)\d{2})", section.strip())

    for block in blocks:
        block = block.strip()
        if not block or len(block) < 8:
            continue
        raw_lines = [l.strip() for l in block.splitlines() if l.strip()]

        if raw_lines and _TABLE_HEADER_RE.match(raw_lines[0]):
            if len(raw_lines) < 2:
                continue
            raw_lines = raw_lines[1:]

        qual = institution = field = description = ""
        start_year = end_year = 0
        is_current = False

        years = year_re.findall(block)

        if len(raw_lines) >= 2:
            parts = [p.strip() for p in raw_lines[0].split("|")]
            if len(parts) >= 2 and not _TABLE_HEADER_RE.match(parts[0]):
                qual = _clean(parts[0])
                institution = _clean(parts[1]) if len(parts) > 1 else ""
                ym = year_re.search(parts[-1]) if parts else None
                if ym:
                    end_year = int(ym.group(1))
                    start_year = end_year - 1
            else:
                qual = _clean(raw_lines[0])
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

        if not qual or len(qual) < 4:
            continue
        if re.match(r"^[@,\s]+$", qual):
            continue
        if _NAME_CAPS_RE.match(qual) and not _EDU_LINE_RE.search(qual):
            continue

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

    for m in _TECH_RE.finditer(source):
        name = _clean(m.group())
        ctx = source[max(0, m.start() - 40):m.end() + 40]
        lm = _LEVEL_RE.search(ctx)
        level = _LEVEL_MAP.get((lm.group(1).lower() if lm else "").replace("-", " "), "intermediate")
        key = name.lower()
        if key not in found:
            found[key] = {"name": name.title(), "level": level, "category": "Technical"}

    if section:
        plain = _TECH_RE.sub("", section)
        for item in re.split(r"[,•|\n/;]+", plain):
            item = _clean(item.lstrip("*•-–> "))
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
    section = (sections.get("LANGUAGE PROFICIENCY") or
               sections.get("LANGUAGES SPOKEN") or
               sections.get("LANGUAGES", ""))
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
                if re.match(r"\b(Mr|Mrs|Ms|Dr|Prof)\b", line) or (
                    _NAME_RE.match(line) and not _EMAIL_RE.search(line) and not _PHONE_RE.search(line)
                ):
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

    sections = _find_sections(text)

    email = _extract_email(text, header_text)
    phone = _extract_phone(text, header_text)
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