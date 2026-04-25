import re
import io
import requests
from bs4 import BeautifulSoup

BASE_URL = 'https://www.dpsa.gov.za'
PSVC_URL = f'{BASE_URL}/newsroom/psvc/'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

EMAIL_RE = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')
SKIP_EMAILS = {'noreply', 'no-reply', 'donotreply', 'webmaster', 'admin', 'info@dpsa', 'privacy'}


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP_EMAILS):
            return m.group(0)
    return ''


def _get_latest_circular():
    """Try multiple strategies to find the latest DPSA circular."""
    try:
        r = requests.get(PSVC_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')

        pattern = re.compile(r'(?:circular[-\s]?(\d+)[-\s]?of[-\s]?(\d{4}))', re.IGNORECASE)
        candidates = []

        for a in soup.find_all('a', href=True):
            href = a['href']
            m = pattern.search(href)
            if not m:
                m = pattern.search(a.get_text())
            if m:
                num, year = int(m.group(1)), int(m.group(2))
                full = href if href.startswith('http') else BASE_URL + href
                candidates.append((year, num, full))
                print(f'[DPSA] Found circular link: {full}')

        if candidates:
            candidates.sort(reverse=True)
            year, num, url = candidates[0]
            print(f'[DPSA] Latest circular: {num} of {year} at {url}')
            return url, num, year

    except Exception as e:
        print(f'[DPSA] Error fetching circular list: {e}')

    # Fallback: guess current circular number based on current year/week
    import datetime
    now = datetime.datetime.now()
    year = now.year
    # Roughly 1 circular per week, ~15 by April
    approx_num = max(1, (now.month * 4) + (now.day // 7))
    fallback_url = f'{BASE_URL}/newsroom/psvc/circular-{approx_num}-of-{year}/'
    print(f'[DPSA] Using fallback circular: {approx_num} of {year}')
    return fallback_url, approx_num, year


def _get_pdf_url(circular_page_url, circ_num, circ_year):
    """Try multiple PDF URL patterns."""
    try:
        r = requests.get(circular_page_url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')

        for a in soup.find_all('a', href=True):
            if a['href'].lower().endswith('.pdf'):
                href = a['href']
                pdf_url = href if href.startswith('http') else BASE_URL + href
                print(f'[DPSA] Found PDF link: {pdf_url}')
                return pdf_url
    except Exception as e:
        print(f'[DPSA] Error fetching circular page: {e}')

    # Try multiple common URL patterns
    padded = str(circ_num).zfill(2)
    candidates = [
        f'{BASE_URL}/dpsa2g/documents/vacancies/{circ_year}/PSV%20CIRCULAR%20{padded}%20of%20{circ_year}.pdf',
        f'{BASE_URL}/dpsa2g/documents/vacancies/{circ_year}/psv%20circular%20{padded}%20of%20{circ_year}.pdf',
        f'{BASE_URL}/dpsa2g/documents/vacancies/{circ_year}/Circular{padded}of{circ_year}.pdf',
        f'{BASE_URL}/dpsa2g/documents/vacancies/{circ_year}/CIRCULAR%20{padded}%20OF%20{circ_year}.pdf',
    ]
    for url in candidates:
        print(f'[DPSA] Trying PDF URL: {url}')
        try:
            head = requests.head(url, headers=HEADERS, timeout=10, allow_redirects=True)
            if head.status_code == 200:
                print(f'[DPSA] PDF found at: {url}')
                return url
        except Exception:
            pass

    return candidates[0]


def _parse_pdf_jobs(pdf_bytes, circ_num, circ_year):
    try:
        import pdfplumber
    except ImportError:
        print('[DPSA] pdfplumber not installed')
        return []

    pages = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        print(f'[DPSA] PDF has {len(pdf.pages)} pages')
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    full_text = '\n'.join(pages)
    print(f'[DPSA] Extracted {len(full_text)} chars from PDF')

    post_pattern = re.compile(r'(?m)^\s*POST\s+(\d+/\d+)\s*:\s*')
    dept_pattern = re.compile(
        r'(?m)^\s*(DEPARTMENT\s+OF[^\n]+|OFFICE\s+OF[^\n]+|[A-Z\s]+ADMINISTRATION[^\n]*)$'
    )
    field_labels = ['SALARY', 'CENTRE', 'REQUIREMENTS', 'DUTIES', 'ENQUIRIES', 'APPLICATIONS', 'NOTE', 'CLOSING DATE']
    field_pattern = re.compile(r'(?m)^\s*(' + '|'.join(field_labels) + r')\s*:\s*')

    splits = list(post_pattern.finditer(full_text))
    print(f'[DPSA] Found {len(splits)} job posts in PDF')
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
        department = re.sub(r'\s+', ' ', dept_matches[-1].group(1).strip()) if dept_matches else 'Unknown Department'

        field_data = {}
        if first_field:
            parts = field_pattern.split(block[first_field.start():])
            it = iter(parts[1:])
            for label in it:
                field_data[label] = re.sub(r'\s+', ' ', next(it, '').strip())

        enquiries = field_data.get('ENQUIRIES', '')
        applications = field_data.get('APPLICATIONS', '')
        closing_date = field_data.get('CLOSING DATE', '')
        salary = field_data.get('SALARY', '')
        centre = field_data.get('CENTRE', 'South Africa')
        email = _find_email(enquiries) or _find_email(applications) or _find_email(block)

        description = ' | '.join(filter(None, [
            field_data.get('REQUIREMENTS', ''),
            field_data.get('DUTIES', ''),
        ]))

        # Build structured how_to_apply
        how_to_apply_parts = []
        if applications:
            how_to_apply_parts.append(f'Applications: {applications}')
        if enquiries:
            how_to_apply_parts.append(f'Enquiries: {enquiries}')
        if closing_date:
            how_to_apply_parts.append(f'Closing Date: {closing_date}')
        how_to_apply = ' | '.join(how_to_apply_parts)

        if not title or len(title) < 4:
            continue

        jobs.append({
            'title': title,
            'company': department,
            'location': centre,
            'description': description[:1200],
            'url': f'{BASE_URL}/newsroom/psvc/circular-{circ_num}-of-{circ_year}',
            'apply_email': email,
            'platform': 'dpsa',
            'salary': salary,
            'job_type': 'Government / Permanent',
            'how_to_apply': how_to_apply,
            '_ref_no': ref_no,
            '_post_ref': f'POST {post_ref}',
            '_circular': f'{circ_num} of {circ_year}',
            '_closing_date': closing_date,
        })

    return jobs


def scrape_dpsa(keywords=None, limit=50):
    try:
        circular_url, circ_num, circ_year = _get_latest_circular()
        if not circular_url:
            print('[DPSA] No circulars found')
            return []

        pdf_url = _get_pdf_url(circular_url, circ_num, circ_year)
        print(f'[DPSA] Downloading PDF: {pdf_url}')
        r = requests.get(pdf_url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        print(f'[DPSA] PDF downloaded: {len(r.content)} bytes')

        jobs = _parse_pdf_jobs(r.content, circ_num, circ_year)
        print(f'[DPSA] Parsed {len(jobs)} jobs from Circular {circ_num} of {circ_year}')

    except Exception as e:
        print(f'[DPSA] Error: {e}')
        import traceback
        traceback.print_exc()
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
