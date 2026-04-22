import re
import io
import requests
from bs4 import BeautifulSoup
from datetime import datetime

BASE_URL = 'https://www.dpsa.gov.za'
PSVC_URL = f'{BASE_URL}/newsroom/psvc/'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

EMAIL_RE = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')
SKIP_EMAILS = {'noreply', 'no-reply', 'donotreply', 'webmaster', 'admin', 'info@dpsa', 'privacy'}


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP_EMAILS):
            return m.group(0)
    return ''


def _get_latest_circular():
    r = requests.get(PSVC_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')

    pattern = re.compile(r'/newsroom/psvc/circular-(\d+)-of-(\d+)/?$', re.IGNORECASE)
    candidates = []
    for a in soup.find_all('a', href=True):
        m = pattern.search(a['href'])
        if m:
            num, year = int(m.group(1)), int(m.group(2))
            href = a['href']
            full = href if href.startswith('http') else BASE_URL + href
            candidates.append((year, num, full))

    if not candidates:
        return None, None, None
    candidates.sort(reverse=True)
    year, num, url = candidates[0]
    return url, num, year


def _get_pdf_url(circular_page_url, circ_num, circ_year):
    r = requests.get(circular_page_url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')

    for a in soup.find_all('a', href=True):
        if a['href'].lower().endswith('.pdf'):
            href = a['href']
            return href if href.startswith('http') else BASE_URL + href

    padded = str(circ_num).zfill(2)
    return (
        f'{BASE_URL}/dpsa2g/documents/vacancies/{circ_year}/'
        f'PSV%20CIRCULAR%20{padded}%20of%20{circ_year}.pdf'
    )


def _parse_pdf_jobs(pdf_bytes, circ_num, circ_year):
    try:
        import pdfplumber
    except ImportError:
        return []

    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    full_text = '\n'.join(pages)

    post_pattern = re.compile(r'(?m)^\s*POST\s+(\d+/\d+)\s*:\s*')
    dept_pattern = re.compile(
        r'(?m)^\s*(DEPARTMENT\s+OF[^\n]+|OFFICE\s+OF[^\n]+|[A-Z\s]+ADMINISTRATION[^\n]*)$'
    )
    field_labels = ['SALARY', 'CENTRE', 'REQUIREMENTS', 'DUTIES', 'ENQUIRIES', 'APPLICATIONS', 'NOTE']
    field_pattern = re.compile(r'(?m)^\s*(' + '|'.join(field_labels) + r')\s*:\s*')

    splits = list(post_pattern.finditer(full_text))
    jobs = []

    for i, match in enumerate(splits):
        post_ref = match.group(1).strip()
        start = match.end()
        end = splits[i + 1].start() if i + 1 < len(splits) else len(full_text)
        block = full_text[start:end].strip()

        first_field = field_pattern.search(block)
        header = block[:first_field.start()].strip() if first_field else block[:200]

        ref_match = re.search(r'REF\s*NO[:\s]+([\w/]+)', header, re.IGNORECASE)
        ref_no = ref_match.group(1).strip() if ref_match else ''
        title = re.sub(r'REF\s*NO[:\s]+[\w/]+', '', header).strip()
        title = re.sub(r'\s+', ' ', title).strip()

        preceding = full_text[max(0, match.start() - 2000):match.start()]
        dept_matches = list(dept_pattern.finditer(preceding))
        department = re.sub(r'\s+', ' ', dept_matches[-1].group(1).strip()) if dept_matches else 'Unknown'

        field_data = {}
        if first_field:
            parts = field_pattern.split(block[first_field.start():])
            it = iter(parts[1:])
            for label in it:
                field_data[label] = re.sub(r'\s+', ' ', next(it, '').strip())

        enquiries = field_data.get('ENQUIRIES', '')
        applications = field_data.get('APPLICATIONS', '')
        email = _find_email(enquiries) or _find_email(applications) or _find_email(block)

        description = ' | '.join(filter(None, [
            field_data.get('REQUIREMENTS', ''),
            field_data.get('DUTIES', ''),
        ]))

        if not title or len(title) < 4:
            continue

        jobs.append({
            'title': title,
            'company': department,
            'location': field_data.get('CENTRE', 'South Africa'),
            'description': description[:800],
            'url': f'{BASE_URL}/newsroom/psvc/circular-{circ_num}-of-{circ_year}',
            'apply_email': email,
            'platform': 'dpsa',
            '_salary': field_data.get('SALARY', ''),
            '_ref_no': ref_no,
            '_post_ref': f'POST {post_ref}',
            '_circular': f'{circ_num} of {circ_year}',
            '_enquiries': enquiries,
            '_applications': applications,
        })

    return jobs


def scrape_dpsa(keywords=None, limit=50):
    try:
        circular_url, circ_num, circ_year = _get_latest_circular()
        if not circular_url:
            print('[DPSA] No circulars found')
            return []

        pdf_url = _get_pdf_url(circular_url, circ_num, circ_year)
        r = requests.get(pdf_url, headers=HEADERS, timeout=60)
        r.raise_for_status()

        jobs = _parse_pdf_jobs(r.content, circ_num, circ_year)
        print(f'[DPSA] Parsed {len(jobs)} jobs from Circular {circ_num} of {circ_year}')

    except Exception as e:
        print(f'[DPSA] Error: {e}')
        return []

    if keywords:
        kws = keywords.lower().split()
        jobs = [j for j in jobs if any(
            kw in j['title'].lower() or kw in j['description'].lower() or kw in j['company'].lower()
            for kw in kws
        )]

    seen, out = set(), []
    for j in jobs:
        key = j['_post_ref']
        if key not in seen:
            seen.add(key)
            out.append(j)

    return out[:limit]
