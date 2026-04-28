import re
import io
import requests
from bs4 import BeautifulSoup
from utils.scraper_utils import job_record, parse_salary_range

BASE_URL = 'https://www.dpsa.gov.za'
PSVC_URL = f'{BASE_URL}/newsroom/psvc/'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-ZA,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Cache-Control': 'max-age=0',
}

EMAIL_RE = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')
SKIP_EMAILS = {'noreply', 'no-reply', 'donotreply', 'webmaster', 'admin', 'info@dpsa', 'privacy'}

GOV_JOB_TYPES = [
    ('internship',  ['internship', ' intern ']),
    ('learnership', ['learnership', 'learner ']),
    ('scholarship', ['scholarship', 'bursary']),
    ('graduate',    ['graduate programme', 'graduate program', 'graduate development']),
    ('entry level', ['entry level', 'entry-level']),
]


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP_EMAILS):
            return m.group(0)
    return ''


def _detect_gov_job_type(title, description='', salary=''):
    text = (title + ' ' + description + ' ' + salary).lower()
    for jtype, terms in GOV_JOB_TYPES:
        if any(t in text for t in terms):
            return jtype
    m = re.search(r'salary level\s+0*([1-7])\b', salary.lower())
    if m:
        return 'entry level'
    return 'Government / Permanent'


def _extract_docs_required(field_data):
    note = field_data.get('NOTE', '')
    applications = field_data.get('APPLICATIONS', '')
    requirements = field_data.get('REQUIREMENTS', '')
    combined = (note + ' ' + applications + ' ' + requirements).lower()

    docs = []
    if 'z83' in combined:
        docs.append('Z83 application form')
    if 'certified cop' in combined:
        docs.append('Certified copies of qualifications & ID')
    if 'curriculum vitae' in combined or re.search(r'\bcv\b', combined):
        docs.append('Curriculum Vitae')
    if 'driver' in combined and 'licen' in combined:
        docs.append("Driver's licence")
    if 'medical certificate' in combined:
        docs.append('Medical certificate')
    if 'police clearance' in combined:
        docs.append('Police clearance certificate')
    if 'security clearance' in combined or 'top secret' in combined:
        docs.append('Security clearance')

    return ', '.join(docs) if docs else ''


def _get_all_circulars(max_circulars=5):
    """Return a list of (url, num, year) for the most recent circulars — not just the latest one."""
    try:
        r = requests.get(PSVC_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')

        pattern = re.compile(r'(?:circular[-\s]?(\d+)[-\s]?of[-\s]?(\d{4}))', re.IGNORECASE)
        candidates = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a['href']
            m = pattern.search(href)
            if not m:
                m = pattern.search(a.get_text())
            if m:
                num, year = int(m.group(1)), int(m.group(2))
                key = (num, year)
                if key not in seen:
                    seen.add(key)
                    full = href if href.startswith('http') else BASE_URL + href
                    candidates.append((year, num, full))

        candidates.sort(reverse=True)
        result = [(url, num, year) for year, num, url in candidates[:max_circulars]]
        print(f'[DPSA] Found {len(result)} circulars to process')
        return result

    except Exception as e:
        print(f'[DPSA] Error fetching circular list: {e}')
        import datetime
        now = datetime.datetime.now()
        year = now.year
        approx_num = max(1, (now.month * 4) + (now.day // 7))
        fallback_url = f'{BASE_URL}/newsroom/psvc/circular-{approx_num}-of-{year}/'
        return [(fallback_url, approx_num, year)]


def _get_pdf_url(circular_page_url, circ_num, circ_year):
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

    padded = str(circ_num).zfill(2)
    candidates = [
        f'{BASE_URL}/dpsa2g/documents/vacancies/{circ_year}/PSV%20CIRCULAR%20{padded}%20of%20{circ_year}.pdf',
        f'{BASE_URL}/dpsa2g/documents/vacancies/{circ_year}/psv%20circular%20{padded}%20of%20{circ_year}.pdf',
        f'{BASE_URL}/dpsa2g/documents/vacancies/{circ_year}/Circular{padded}of{circ_year}.pdf',
        f'{BASE_URL}/dpsa2g/documents/vacancies/{circ_year}/CIRCULAR%20{padded}%20OF%20{circ_year}.pdf',
    ]
    for url in candidates:
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
        salary_raw = field_data.get('SALARY', '')
        centre = field_data.get('CENTRE', 'South Africa')
        requirements_text = field_data.get('REQUIREMENTS', '')
        duties_text = field_data.get('DUTIES', '')
        email = _find_email(enquiries) or _find_email(applications) or _find_email(block)

        # Build requirements and duties as lists (split on bullet/newline patterns)
        def _split_field(text):
            if not text:
                return []
            lines = re.split(r'(?:\n|;|•|–)\s*', text)
            return [l.strip() for l in lines if len(l.strip()) > 8][:15]

        how_to_apply_parts = []
        if applications:
            how_to_apply_parts.append(f'Applications: {applications}')
        if enquiries:
            how_to_apply_parts.append(f'Enquiries: {enquiries}')
        if closing_date:
            how_to_apply_parts.append(f'Closing Date: {closing_date}')

        description = ' | '.join(filter(None, [requirements_text, duties_text]))

        if not title or len(title) < 4:
            continue

        # ── Option 5 schema via job_record() ──────────────────────────────────
        jobs.append(job_record({
            'title': title,
            'company': department,
            'location': centre,
            'salary': salary_raw,
            'job_type': _detect_gov_job_type(title, description, salary_raw),
            'closing_date': closing_date,
            'apply_email': email,
            'requirements': _split_field(requirements_text),
            'duties': _split_field(duties_text),
            'how_to_apply': ' | '.join(how_to_apply_parts),
            'docs_required': _extract_docs_required(field_data),
            'url': f'{BASE_URL}/newsroom/psvc/circular-{circ_num}-of-{circ_year}',
            'platform': 'dpsa',
            'description': description[:2000],
            'raw_text': block[:3000],
            # DPSA-specific extras stored so scrape_jobs can use them
            '_ref_no': ref_no,
            '_post_ref': f'POST {post_ref}',
            '_circular': f'{circ_num} of {circ_year}',
            '_closing_date': closing_date,
        }))

    return jobs


def scrape_dpsa(keywords=None, limit=500):
    """
    Scrape ALL available DPSA circulars (up to 5 most recent).
    No artificial limit — returns everything found, deduped by POST ref.
    `limit` is a safety cap; default 500 is effectively uncapped for normal circulars.
    """
    all_jobs = []
    seen_posts = set()

    circulars = _get_all_circulars(max_circulars=5)

    for circular_url, circ_num, circ_year in circulars:
        try:
            pdf_url = _get_pdf_url(circular_url, circ_num, circ_year)
            print(f'[DPSA] Downloading PDF for circular {circ_num}/{circ_year}: {pdf_url}')
            r = requests.get(pdf_url, headers=HEADERS, timeout=90)
            r.raise_for_status()
            print(f'[DPSA] PDF downloaded: {len(r.content):,} bytes')

            jobs = _parse_pdf_jobs(r.content, circ_num, circ_year)
            print(f'[DPSA] Parsed {len(jobs)} jobs from circular {circ_num}/{circ_year}')

            for j in jobs:
                key = j.get('_post_ref', j['title'])
                if key not in seen_posts:
                    seen_posts.add(key)
                    # Apply keyword filter if specified
                    if keywords:
                        kws = keywords.lower().split()
                        text = (j['title'] + ' ' + j['description']).lower()
                        if not any(kw in text for kw in kws):
                            continue
                    all_jobs.append(j)

        except Exception as e:
            print(f'[DPSA] Error processing circular {circ_num}/{circ_year}: {e}')
            import traceback
            traceback.print_exc()
            continue

    print(f'[DPSA] Total unique jobs across all circulars: {len(all_jobs)} → returning up to {limit}')
    return all_jobs[:limit]
