# apps/scraper/scrapers/jobmail.py

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

# Emails that belong to the platform itself, not the employer
_PLATFORM_EMAIL_DOMAINS = {
    'jobmail.co.za', 'gumtree.co.za', 'careers24.com',
    'pnet.co.za', 'careerjunction.co.za', 'communicate.co.za',
}


def _clean(t):
    return re.sub(r'\s+', ' ', t or '').strip()


def _extract_id(url):
    m = re.search(r'-id-(\d+)', url)
    return m.group(1) if m else ''


def _is_platform_email(email: str) -> bool:
    """Return True if email belongs to a job board or recruiter platform, not a real employer."""
    domain = email.lower().split('@')[-1] if '@' in email else ''
    return domain in _PLATFORM_EMAIL_DOMAINS


def _extract_contact_email(raw_text: str) -> str:
    """Extract email from Contact [Name] on [email] pattern."""
    m = re.search(
        r'Contact\s+\w[\w\s]+\s+on\s+([\w.+-]+@[\w.-]+\.[a-zA-Z]{2,})',
        raw_text, re.IGNORECASE
    )
    if m:
        return m.group(1)
    # Also catch "email: addr" or "e-mail: addr"
    m = re.search(
        r'e-?mail[:\s]+([^\s,<>]+@[^\s,<>]+\.[a-zA-Z]{2,})',
        raw_text, re.IGNORECASE
    )
    if m:
        return m.group(1)
    return ''


def _parse_listing_page(html, keywords=None):
    soup = BeautifulSoup(html, 'html.parser')
    cards = []
    seen_ids = set()

    for a in soup.find_all('a', href=re.compile(r'/jobs/.+-id-\d+')):
        href = a.get('href', '')
        job_id = _extract_id(href)
        if not job_id or job_id in seen_ids:
            continue

        # Skip pagination/nav links — they wrap large blocks of text
        # Real job title links are short and don't contain newlines
        raw_text = a.get_text(separator=' ')
        title = _clean(raw_text)

        # Filter out search-result page links (e.g. "5 Architect jobs in Gauteng on Job Mail")
        if re.search(r'\d+\s+\w+\s+jobs?\s+in\b', title, re.IGNORECASE):
            continue
        if not title or len(title) < 3 or len(title) > 120:
            continue
        # Skip if it reads like a sentence (pagination text tends to be long)
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

    title_el = soup.select_one('h1')
    title = _clean(title_el.get_text()) if title_el else ''
    if not title:
        return None

    # Skip search-results pages that slipped through
    if re.search(r'\d+\s+\w+\s+jobs?\s+in\b', title, re.IGNORECASE):
        return None

    comp_m = re.search(r'(?:Recruiter|Company|Employer|Posted\s+by)[:\s]+([^\n]+)', raw_text, re.I)
    company = _clean(comp_m.group(1)) if comp_m else ''

    loc_el = soup.select_one('[class*="location"], [data-qa*="location"], [itemprop="addressLocality"]')
    location = _clean(loc_el.get_text()) if loc_el else ''
    if not location:
        loc_m = re.search(r'(?:Location|City|Area|Province)[:\s]+([^\n]+)', raw_text, re.I)
        location = _clean(loc_m.group(1)) if loc_m else 'South Africa'

    salary_m = re.search(r'(R[\d ,]+(?:\s*[-–]\s*R[\d ,]+)?|Market\s+Related|Negotiable|CTC)', raw_text, re.I)
    salary = _clean(salary_m.group(0)) if salary_m else ''

    job_type_m = re.search(
        r'\b(permanent|contract|temporary|internship|learnership|part[- ]time|full[- ]time)\b',
        raw_text, re.I
    )
    job_type = job_type_m.group(0).title() if job_type_m else ''

    # Extract description — use semantic selectors first, fall back to text between markers
    description = ''
    for sel in ['.job-description', '.description', '[class*="job-detail"]', 'article', '.content', 'main']:
        el = soup.select_one(sel)
        if el:
            description = _clean(el.get_text('\n'))
            break

    if not description:
        desc_m = re.search(
            r'Apply Now\s*(.+?)(?:Apply Now|Create your FREE|Get notified|Sign in)',
            raw_text, re.DOTALL | re.IGNORECASE
        )
        if desc_m:
            description = _clean(desc_m.group(1))

    # Strip recruiter boilerplate from description
    description = re.sub(
        r'Connect\s+with\s+us\s+on\s+www\..+$', '', description, flags=re.DOTALL | re.IGNORECASE
    ).strip()
    description = re.sub(
        r'Register\s+your\s+CV\s+to\s+create.+$', '', description, flags=re.DOTALL | re.IGNORECASE
    ).strip()

    how_to_apply_m = re.search(
        r'(?:How\s+to\s+Apply|To\s+Apply|Send.*?CV|Forward.*?CV|'
        r'Application\s+Process|Apply\s+(?:via|by|to))[:\s]*([^\n]{10,300})',
        raw_text, re.I
    )
    how_to_apply = _clean(how_to_apply_m.group(1)) if how_to_apply_m else ''

    # Email: try contact-name pattern first (common on JobMail)
    apply_email = _extract_contact_email(raw_text)

    # Fall back to standard priority extraction, skipping platform-owned emails
    if not apply_email:
        apply_email = extract_email_priority(
            how_to_apply=how_to_apply,
            description=description,
            raw_text=raw_text,
        )

    # Never store a platform/job-board email as the apply email
    if apply_email and _is_platform_email(apply_email):
        apply_email = ''

    closing_date = extract_closing_date(raw_text)

    phone_m = PHONE_RE.search(raw_text)
    phone = _clean(phone_m.group(0)) if phone_m else ''

    req_m = re.search(
        r'(?:Requirements?|Minimum\s+Requirements?|Qualifications?)[:\s]*\n+(.*?)(?:\n{2,}|$)',
        raw_text, re.DOTALL | re.I
    )
    requirements = _clean(req_m.group(1))[:500] if req_m else ''

    duties_m = re.search(
        r'(?:Duties|Responsibilities|Key\s+Responsibilities)[:\s]*\n+(.*?)(?:\n{2,}|$)',
        raw_text, re.DOTALL | re.I
    )
    duties = _clean(duties_m.group(1))[:500] if duties_m else ''

    if len(description) < 200:
        description = ' | '.join(filter(None, [description, requirements, duties]))

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