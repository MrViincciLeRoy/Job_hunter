# CV Extractor

Drop-in replacement for `apps/accounts/cv_extractor.py`. Same `parse_cv()` API, dramatically better accuracy on complex layouts.

## What changed

**Old approach**: pdfplumber/pypdf dump text linearly → regex on garbled output.  
**New approach**: PyMuPDF extracts every text block with its bounding-box coordinates → column detection → correct reading order → then regex parsing on clean text.

Key improvements:
- **Multi-column layout support** — detects sidebar vs main content columns using x-coordinate clustering, reconstructs reading order per column
- **Split-date joining** — dates broken across lines by column extraction are rejoined before parsing (e.g., `"01-2024 -\nDec 2024"` → `"01-2024 - Dec 2024"`)
- **Header-area extraction** — name, phone, and email are pulled from the top 30% of page 1 only, avoiding reference section phones bleeding into candidate contact
- **Split-name detection** — handles names on two consecutive lines (e.g., `"RONDA"` / `"CHAUKE"`)
- **Section map** — `_find_sections()` builds a dict of all sections once; all extractors read from it instead of re-scanning the full text
- **Orphaned-date recovery** — if date ranges appear in a separate column that ends up at the bottom of the text, they're matched back to job entries by order

## Install

```
pip install pymupdf pdfplumber pypdf
```

PyMuPDF is the primary engine. pdfplumber and pypdf are automatic fallbacks.

## Usage

```python
from cv_extractor import parse_cv

with open("resume.pdf", "rb") as f:
    data = parse_cv(f.read())

# Returns:
{
    "first_name": "Ronda",
    "last_name": "Chauke",
    "phone": "+27832157868",
    "location": "11th Street, Kempton Park",
    "occupation": "",
    "years_experience": "1-2",
    "bio": "Results-driven Chemistry graduate...",
    "linkedin_url": "",
    "github_url": "",
    "portfolio_url": "",
    "work_experiences": [...],
    "educations": [...],
    "skills": [...],
    "languages": [...],
    "references": [...],
}
```

Pass `mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"` for `.docx` files (requires `docx2txt`).

## Tested layouts

Passes 12/12 across these template styles: single-column, left sidebar, right sidebar, 2-column with icon contacts, teal header, dark sidebar, salmon boxes, navy banner, circular skill charts, centered header.
