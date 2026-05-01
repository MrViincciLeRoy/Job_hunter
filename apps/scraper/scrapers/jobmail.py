import re
import json
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

# Tighter pattern: requires at least 4 digits (R1 000 minimum) to avoid R0/R2 garbage.
# Handles: R50 000,00 | R50,000 | R50000 | R1 500 000 | ranges with –
_SALARY_RE = re.compile(
    r'(?<![A-Za-z@])'
    r'R\s*\d{1,3}(?:[\s\u00a0]\d{3})*(?:[.,]\d{2})?'       # e.g. R50 000,00
    r'(?:\s*[-–]\s*R\s*\d{1,3}(?:[\s\u00a0]\d{3})*(?:[.,]\d{2})?)?'  # optional – R60 000,00
    r'(?:\s*\(PER\s+(?:MONTH|YEAR|ANNUM)\))?',
    re.IGNORECASE,
)

_MIN_SALARY_DIGITS = 4   # must have at least 4 consecutive digits to be a real salary


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


def _extract_salary_jsonld(soup) -> str:
    """Pull salary from the JobPosting JSON-LD block — always accurate when present."""
    tag = soup.find('script', type='application/ld+json', id='JobPosting')
    if not tag:
        tag = soup.find('script', type='application/ld+json')
    if not tag:
        return ''
    try:
        data = json.loads(tag.string or '')
        if data.get('@type') != 'JobPosting':
            return ''
        bs = data.get('baseSalary', {})
        val = bs.get('value', {})
        mn  = val.get('minValue')
        mx  = val.get('maxValue')
        unit = val.get('unitText', '')
        currency = bs.get('currency', 'ZAR')
        if mn and mx and mn != mx:
            return f'R{int(mn):,} – R{int(mx):,} ({unit})'
        elif mn:
            return f'R{int(mn):,} ({unit})'
    except Exception:
        pass
    return ''


def _extract_salary_html(soup) -> str:
    """Pull from the structured salary element on the detail page."""
    for sel in [
        'a.details-salary-range b',
        '.details-salary-range b',
        '[class*="salary"] b',
        '[class*="salary-range"] b',
    ]:
        el = soup.select_one(sel)
        if el:
            txt = _clean(el.get_text())
            # Confirm it looks like a real ZAR amount (has digits)
            if re.search(r'\d{3}', txt):
                return txt
    # Fallback: full salary container text
    for sel in ['a.details-salary-range', '.details-salary-range']:
        el = soup.select_one(sel)
        if el:
            txt = _clean(el.get_text())
            if re.search(r'R\s*\d{3}', txt):
                return txt
    return ''


def _extract_salary_text(raw_text: str) -> str:
    """Regex extraction from raw text — last resort, filtered to avoid garbage."""
    for m in _SALARY_RE.finditer(raw_text):
        candidate = _clean(m.group(0))
        # Must contain at least _MIN_SALARY_DIGITS consecutive digits
        digits = re.sub(r'[^\d]', '', candidate)
        if len(digits) >= _MIN_SALARY_DIGITS:
            return candidate
    # Soft fallbacks
    soft = re.search(r'\b(Market\s+Related|Negotiable|CTC|TBC)\b', raw_text, re.I)
    return _clean(soft.group(0)) if soft else ''


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

    # ── Job Type ─────────────────────────────────────────────────────────────
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

    # ── Salary — 3-tier priority ──────────────────────────────────────────────
    # 1. JSON-LD (most reliable — set by the site)
    salary = _extract_salary_jsonld(soup)
    # 2. Structured HTML element
    if not salary:
        salary = _extract_salary_html(soup)
    # 3. Regex over raw text (catches salary buried in job summary)
    if not salary:
        salary = _extract_salary_text(raw_text)

    # ── Description ──────────────────────────────────────────────────────────
    description = ''
    job_id = _extract_id(url) or '0'
    for sel in [
        f'#pills-job-spec-{job_id} .card-body',
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