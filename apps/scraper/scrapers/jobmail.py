import re
import time
import random
import requests
from bs4 import BeautifulSoup
from .async_http import parallel_fetch
from utils.scraper_utils import (
    random_headers, job_record,
    extract_email_priority, extract_closing_date,
)

BASE_URL  = 'https://www.jobmail.co.za'
START_URL = 'https://www.jobmail.co.za/jobs/it-computer?sort=latest'

PHONE_RE = re.compile(r'(\+27|0)[0-9()\s-]{8,14}')

_PLATFORM_EMAIL_DOMAINS = {
    'jobmail.co.za', 'gumtree.co.za', 'careers24.com',
    'pnet.co.za', 'careerjunction.co.za', 'communicate.co.za',
}

# Salary: word boundary before R, SA format R156 000,00 or R156,000 or R156000
_SALARY_RE = re.compile(
    r'(?<![A-Za-z])'                             # not preceded by a letter
    r'R\s*\d[\d\s]*(?:[.,]\d{2})?'              # R + number (e.g. R156 000,00)
    r'(?:\s*[-–]\s*R\s*\d[\d\s]*(?:[.,]\d{2})?)?' # optional range
    r'(?:\s*\([^)]{1,30}\))?',                   # optional "(PER YEAR)"
    re.IGNORECASE,
)


def _clean(t):
    return re.sub(r'\s+', ' ', t or '').strip()


def _extract_id(url):
    m = re.search(r'-id-(\d+)', url)
    return m.group(1) if m else ''


def _is_platform_email(email: str) -> bool:
    domain = email.lower().split('@')[-1] if '@' in email else ''
    return domain in _PLATFORM_EMAIL_DOMAINS


def _extract_contact_email(raw_text: str) -> str:
    m = re.search(
        r'Contact\s+\w[\w\s]+\s+on\s+([\w.+-]+@[\w.-]+\.[a-zA-Z]{2,})',
        raw_text, re.IGNORECASE
    )
    if m:
        return m.group(1)
    m = re.search(
        r'e-?mail[:\s]+([^\s,<>]+@[^\s,<>]+\.[a-zA-Z]{2,})',
        raw_text, re.IGNORECASE
    )
    return m.group(1) if m else ''


def _parse_listing_page(html, keywords=None):
    soup = BeautifulSoup(html, 'html.parser')
    cards = []
    seen_ids = set()

    for a in soup.find_all('a', href=re.compile(r'/jobs/.+-id-\d+')):
        href = a.get('href', '')
        job_id = _extract_id(href)
        if not job_id or job_id in seen_ids:
            continue

        raw_text = a.get_text(separator=' ')
        title = _clean(raw_text)

        if re.search(r'\d+\s+\w+\s+jobs?\s+in\b', title, re.IGNORECASE):
            continue
        if not title or len(title) < 3 or len(title) > 120:
            continue
        if title.count(' ') > 10:
            continue

        seen_ids.add(job_id)
        parts = href.strip('/').split('/')
        location = parts[3].replace('-', ' ').title() if len(parts) > 3 else 'South Africa'
        full_url = href if href.startswith('http') else BASE_URL + href
        cards.append({'job_id': job_id, 'title': title, 'location': location, 'url': full_url})

    if keywords:
        kws = keywords.lower().split()
        cards = [c for c in cards if any(kw in c['title'].lower() for kw in kws)]

    return cards


def _scrape_detail(url):
    try:
        r = requests.get(url, headers=random_headers(), timeout=20)
        r.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(r.text, 'html.parser')
    raw_text = soup.get_text(separator='\n', strip=True)

    # ── Title ────────────────────────────────────────────────────────────────
    title = ''
    for sel in ['h1.text-primary', 'h1.h3', '.company-details h1', 'h1']:
        el = soup.select_one(sel)
        if el:
            title = _clean(el.get_text())
            break
    if not title:
        return None
    if re.search(r'\d+\s+\w+\s+jobs?\s+in\b', title, re.IGNORECASE):
        return None

    # ── Company ──────────────────────────────────────────────────────────────
    company = ''
    for sel in ['a.details-company', '.details-company', 'span.recruiter']:
        el = soup.select_one(sel)
        if el:
            company = _clean(el.get_text())
            break
    if not company:
        m = re.search(r'(?:Recruiter|Company|Employer|Posted\s+by)[:\s]+([^\n]+)', raw_text, re.I)
        company = _clean(m.group(1)) if m else ''

    # ── Location ─────────────────────────────────────────────────────────────
    location = ''
    for sel in ['span.details-job-location', 'div.details-job-location', '[class*="job-location"]']:
        el = soup.select_one(sel)
        if el:
            location = _clean(el.get_text())
            break
    if not location:
        m = re.search(r'(?:Location|City|Area|Province)[:\s]+([^\n]+)', raw_text, re.I)
        location = _clean(m.group(1)) if m else 'South Africa'

    # ── Job Type — selector first, then regex with optional hyphen/space ─────
    job_type = ''
    for sel in ['span.details-job-type', '[class*="job-type"]']:
        el = soup.select_one(sel)
        if el:
            job_type = _clean(el.get_text())
            break
    if not job_type:
        m = re.search(
            r'\b(permanent|contract|temporary|internship|learnership|'
            r'part[- ]?time|full[- ]?time)\b',
            raw_text, re.I
        )
        job_type = m.group(0).title() if m else ''

    # ── Salary — strict word-boundary pattern to avoid matching "r" in words ─
    salary = ''
    sal_m = _SALARY_RE.search(raw_text)
    if sal_m:
        salary = _clean(sal_m.group(0))
    if not salary:
        m2 = re.search(r'\b(Market\s+Related|Negotiable|CTC|TBC)\b', raw_text, re.I)
        salary = _clean(m2.group(0)) if m2 else ''

    # ── Description — target the active job-spec card body ───────────────────
    description = ''
    for sel in [
        '#pills-job-spec-' + (_extract_id(url) or '0') + ' .card-body',
        '.tab-pane.active .card-body',
        '.tab-pane.show .card-body',
        '.card-body',
        'article',
        'main',
    ]:
        el = soup.select_one(sel)
        if el:
            txt = _clean(el.get_text('\n'))
            if len(txt) > 100:
                description = txt
                break

    # Strip recruiter boilerplate
    for pat in [
        r'Connect\s+with\s+us\s+on\s+www\..+$',
        r'Register\s+your\s+CV\s+to\s+create.+$',
        r'One\s+of\s+the\s+best\s+Developer\s+Recruitment.+$',
    ]:
        description = re.sub(pat, '', description, flags=re.DOTALL | re.IGNORECASE).strip()

    # ── How to apply ─────────────────────────────────────────────────────────
    m = re.search(
        r'(?:How\s+to\s+Apply|To\s+Apply|Send.*?CV|Forward.*?CV|'
        r'Application\s+Process|Apply\s+(?:via|by|to))[:\s]*([^\n]{10,300})',
        raw_text, re.I
    )
    how_to_apply = _clean(m.group(1)) if m else ''

    # ── Email ─────────────────────────────────────────────────────────────────
    apply_email = _extract_contact_email(raw_text)
    if not apply_email:
        apply_email = extract_email_priority(
            how_to_apply=how_to_apply,
            description=description,
            raw_text=raw_text,
        )
    if apply_email and _is_platform_email(apply_email):
        apply_email = ''

    # ── Phone / closing date ──────────────────────────────────────────────────
    phone_m = PHONE_RE.search(raw_text)
    phone        = _clean(phone_m.group(0)) if phone_m else ''
    closing_date = extract_closing_date(raw_text)

    # ── Pad short descriptions ────────────────────────────────────────────────
    if len(description) < 200:
        req_m = re.search(
            r'(?:Requirements?|Minimum\s+Requirements?)[:\s]*\n+(.*?)(?:\n{2,}|$)',
            raw_text, re.DOTALL | re.I
        )
        duties_m = re.search(
            r'(?:Duties|Responsibilities|Key\s+Responsibilities)[:\s]*\n+(.*?)(?:\n{2,}|$)',
            raw_text, re.DOTALL | re.I
        )
        extras = [
            _clean(req_m.group(1))[:500]    if req_m    else '',
            _clean(duties_m.group(1))[:500] if duties_m else '',
        ]
        description = ' | '.join(filter(None, [description] + extras))

    return job_record({
        'title':        title,
        'company':      company,
        'location':     location,
        'salary':       salary,
        'job_type':     job_type,
        'closing_date': closing_date,
        'apply_email':  apply_email,
        'phone':        phone,
        'how_to_apply': how_to_apply,
        'url':          url,
        'platform':     'jobmail',
        'description':  description[:2000],
        'raw_text':     raw_text[:3000],
    })


def _collect_links(keywords, max_pages=20):
    session = requests.Session()
    session.headers.update(random_headers())
    all_cards = []
    seen_ids = set()
    consecutive_empty = 0

    urls_to_try = []
    if keywords:
        q = keywords.strip().replace(' ', '-').lower()
        urls_to_try.append(f'{BASE_URL}/jobs/{q}?sort=latest')
        urls_to_try.append(f'{BASE_URL}/jobs/it-computer?q={keywords.replace(" ", "+")}&sort=latest')
    urls_to_try.append(START_URL)

    for start_url in urls_to_try:
        for pg in range(1, max_pages + 1):
            url = start_url if pg == 1 else f'{start_url.split("?")[0]}/page{pg}?sort=latest'

            session.headers.update(random_headers())
            try:
                r = session.get(url, timeout=25)
                r.raise_for_status()
                cards = _parse_listing_page(r.text, keywords)
                new_cards = [c for c in cards if c['job_id'] not in seen_ids]

                if not new_cards:
                    consecutive_empty += 1
                    if consecutive_empty >= 2:
                        print(f'[JobMail] No new cards at page {pg}, stopping')
                        break
                else:
                    consecutive_empty = 0

                for c in new_cards:
                    seen_ids.add(c['job_id'])
                all_cards.extend(new_cards)
                print(f'[JobMail] Page {pg}: {len(new_cards)} new cards (total: {len(all_cards)})')
                time.sleep(random.uniform(0.8, 2.0))

            except Exception as e:
                print(f'[JobMail] Page {pg} error: {e}')
                time.sleep(random.uniform(2.0, 4.0))
                break

        if all_cards:
            break

    return all_cards


def scrape_jobmail(keywords=None, limit=500):
    cards = _collect_links(keywords, max_pages=20)
    if not cards:
        print('[JobMail] No jobs found')
        return []

    urls = [c['url'] for c in cards[:limit]]
    print(f'[JobMail] Fetching {len(urls)} detail pages in parallel (workers=14)...')
    jobs = parallel_fetch(urls, _scrape_detail, max_workers=14)
    jobs = [j for j in jobs if j and j.get('title')]
    print(f'[JobMail] {len(jobs)} jobs scraped')
    return jobs