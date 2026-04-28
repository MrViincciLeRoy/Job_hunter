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

# Priority tiers for job types (higher = more interesting to surface first)
JOB_TYPE_PRIORITY = {
    'internship':  10,
    'learnership': 9,
    'bursary':     8,
    'scholarship': 8,
    'graduate':    7,
    'entry level': 6,
    'Government / Permanent': 1,
}

GOV_JOB_TYPES = [
    # Check longest/most-specific terms first to avoid false matches
    ('internship',  ['internship programme', 'internship program', 'internship (', 'internship:', 'internship\n', 'internship ']),
    ('learnership', ['learnership programme', 'learnership program', 'learnership (', 'learnership:', 'learnership\n', 'learnership ']),
    ('bursary',     ['bursary programme', 'bursary program', 'bursary (', 'bursary:', 'bursary\n', 'bursary ']),
    ('scholarship', ['scholarship programme', 'scholarship']),
    ('graduate',    ['graduate programme', 'graduate program', 'graduate development']),
    ('entry level', ['entry level', 'entry-level']),
]

# Qualifications that indicate low barrier to entry
LOW_BARRIER_QUALS = [
    'grade 10', 'grade 11', 'grade 12', 'abet', 'matric',
    'std 8', 'std 9', 'std 10', 'no experience', 'no formal',
]

# Regex to detect minimum qualification level from requirements text
GRADE_RE = re.compile(r'grade\s+(\d+)', re.IGNORECASE)
NQF_RE = re.compile(r'nqf\s+level\s+(\d+)', re.IGNORECASE)
SALARY_LEVEL_RE = re.compile(r'salary level\s+0*(\d+)', re.IGNORECASE)


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
    m = SALARY_LEVEL_RE.search(salary.lower())
    if m and int(m.group(1)) <= 5:
        return 'entry level'
    return 'Government / Permanent'


def _is_low_barrier(requirements_text):
    """True if the job needs Grade 12 or less / ABET / no experience."""
    t = requirements_text.lower()
    if any(q in t for q in LOW_BARRIER_QUALS):
        # Make sure there's no higher qualification also mentioned
        has_degree = any(w in t for w in ['degree', 'diploma', 'bachelor', 'honours', 'postgraduate', 'llb', 'b.com'])
        if not has_degree:
            return True
    return False


def _check_qualification_match(requirements_text, user_qualifications=None):
    """
    Check if user meets or exceeds the minimum requirements.
    Returns: 'exceeds' | 'meets' | 'below' | 'unknown'
    user_qualifications: list of strings e.g. ['grade 12', 'diploma']
    If not provided, assumes Grade 12 as baseline.
    """
    if user_qualifications is None:
        user_qualifications = ['grade 12', 'matric']

    t = requirements_text.lower()
    user_t = ' '.join(user_qualifications).lower()

    # Detect minimum grade required
    grade_m = GRADE_RE.search(t)
    if grade_m:
        min_grade = int(grade_m.group(1))
        user_grade_m = GRADE_RE.search(user_t)
        user_grade = int(user_grade_m.group(1)) if user_grade_m else 12
        if user_grade > min_grade:
            return 'exceeds'
        elif user_grade == min_grade:
            return 'meets'
        else:
            return 'below'

    # No grade requirement found — check for degree/diploma
    needs_degree = any(w in t for w in ['degree', 'diploma', 'bachelor', 'honours', 'postgraduate', 'llb'])
    has_degree = any(w in user_t for w in ['degree', 'diploma', 'bachelor', 'honours', 'postgraduate'])
    if needs_degree and not has_degree:
        return 'below'
    if needs_degree and has_degree:
        return 'meets'

    return 'unknown'


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


def _parse_stipend(stipend_text):
    """
    Internship stipends look like:
    'A stipend will be paid ... Diploma/Degree/Honours R7860.50 and Master's R9482.00 per month'
    Extract the range or the base amount.
    """
    if not stipend_text:
        return stipend_text
    # Try to extract R amounts
    amounts = re.findall(r'R[\d\s,]+(?:\.\d+)?', stipend_text)
    if amounts:
        cleaned = [a.strip() for a in amounts]
        if len(cleaned) >= 2:
            return f"{cleaned[0]} – {cleaned[-1]} per month (stipend)"
        return f"{cleaned[0]} per month (stipend)"
    return stipend_text.strip()[:200]


def _get_all_circulars(max_circulars=5):
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

    # STIPEND added — critical for internship posts
    field_labels = [
        'SALARY', 'STIPEND', 'CENTRE', 'REQUIREMENTS', 'DUTIES',
        'ENQUIRIES', 'APPLICATIONS', 'NOTE', 'CLOSING DATE',
    ]
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

        ref_match = re.search(r'REF\s*NO[:\s]+([\w/\s]+?)(?:\n|$)', header, re.IGNORECASE)
        ref_no = ref_match.group(1).strip() if ref_match else ''
        title = re.sub(r'REF\s*NO[:\s]+[\w/\s]+', '', header).strip()
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
        requirements_text = field_data.get('REQUIREMENTS', '')
        duties_text = field_data.get('DUTIES', '')
        centre = field_data.get('CENTRE', 'South Africa')

        # Handle both SALARY and STIPEND fields
        salary_raw = field_data.get('SALARY', '')
        stipend_raw = field_data.get('STIPEND', '')
        is_internship_stipend = bool(stipend_raw and not salary_raw)
        if is_internship_stipend:
            salary_raw = _parse_stipend(stipend_raw)

        email = _find_email(enquiries) or _find_email(applications) or _find_email(block)

        job_type = _detect_gov_job_type(title, requirements_text + ' ' + duties_text, salary_raw)

        # Low-barrier flag — Grade 12 / ABET only
        low_barrier = _is_low_barrier(requirements_text) and job_type not in ('internship', 'learnership', 'bursary')

        # Qualification match check (baseline: Grade 12)
        qual_match = _check_qualification_match(requirements_text)

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

        # Priority score: internships/learnerships/bursaries first, then low-barrier, then rest
        priority = JOB_TYPE_PRIORITY.get(job_type, 1)
        if low_barrier:
            priority = max(priority, 5)  # bump low-barrier above regular gov jobs

        jobs.append(job_record({
            'title': title,
            'company': department,
            'location': centre,
            'salary': salary_raw,
            'job_type': job_type,
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
            # DPSA-specific extras
            '_ref_no': ref_no,
            '_post_ref': f'POST {post_ref}',
            '_circular': f'{circ_num} of {circ_year}',
            '_closing_date': closing_date,
            '_is_internship_stipend': is_internship_stipend,
            '_low_barrier': low_barrier,
            '_qual_match': qual_match,   # 'exceeds' | 'meets' | 'below' | 'unknown'
            '_priority': priority,
        }))

    # Sort: highest priority first, then by closing date proximity
    jobs.sort(key=lambda j: -j.get('_priority', 1))
    return jobs


def scrape_dpsa(keywords=None, limit=500):
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

    # Final sort: priority desc, then internships/learnerships/bursaries float to top
    all_jobs.sort(key=lambda j: -j.get('_priority', 1))

    counts = {}
    for j in all_jobs:
        jt = j.get('job_type', 'other')
        counts[jt] = counts.get(jt, 0) + 1
    print(f'[DPSA] Job type breakdown: {counts}')
    print(f'[DPSA] Total unique jobs: {len(all_jobs)} → returning up to {limit}')

    return all_jobs[:limit]