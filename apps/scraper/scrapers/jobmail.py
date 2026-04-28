import re
import time
import random
import requests
from bs4 import BeautifulSoup
from .async_http import parallel_fetch
from utils.scraper_utils import random_headers, job_record

BASE_URL  = 'https://www.jobmail.co.za'
START_URL = 'https://www.jobmail.co.za/jobs/it-computer?sort=latest'

EMAIL_RE = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')
SKIP_EMAILS = {
    'noreply', 'no-reply', 'donotreply',
    'support@jobmail', 'info@jobmail', 'privacy@jobmail',
    'help@jobmail', 'legal@jobmail',
}
PHONE_RE = re.compile(r'(\+27|0)[0-9()\s-]{8,14}')


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP_EMAILS):
            return m.group(0)
    return ''


def _clean(t):
    return re.sub(r'\s+', ' ', t or '').strip()


def _extract_id(url):
    m = re.search(r'-id-(\d+)', url)
    return m.group(1) if m else ''


def _parse_listing_page(html, keywords=None):
    soup = BeautifulSoup(html, 'html.parser')
    cards = []
    seen_ids = set()

    # Primary pattern: /jobs/{cat}/{location}/{slug}-id-{id}
    for a in soup.find_all('a', href=re.compile(r'/jobs/.+-id-\d+')):
        href = a.get('href', '')
        job_id = _extract_id(href)
        if not job_id or job_id in seen_ids:
            continue
        seen_ids.add(job_id)
        title = _clean(a.get_text())
        if not title or len(title) < 3:
            continue
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

    comp_m = re.search(r'(?:Recruiter|Company|Employer)[:\s]+([^\n]+)', raw_text, re.I)
    company = _clean(comp_m.group(1)) if comp_m else ''

    loc_m = re.search(r'(?:Location|City|Area)[:\s]+([^\n]+)', raw_text, re.I)
    location = _clean(loc_m.group(1)) if loc_m else 'South Africa'

    salary_m = re.search(r'(R[\d ,]+(?:\s*[-–]\s*R[\d ,]+)?|Market Related|Negotiable|CTC)', raw_text, re.I)
    salary = _clean(salary_m.group(0)) if salary_m else ''

    job_type_m = re.search(r'(permanent|contract|temporary|internship|learnership|part.time|full.time)', raw_text, re.I)
    job_type = job_type_m.group(0).title() if job_type_m else ''

    # Description: grab the main body block
    desc_m = re.search(
        r'Apply Now\s*(.+?)(?:Apply Now|Create your FREE|Get notified|Sign in)',
        raw_text, re.DOTALL | re.IGNORECASE
    )
    description = _clean(desc_m.group(1)) if desc_m else ''
    if not description:
        for sel in ['.job-description', '.description', 'article', '.content', 'main']:
            el = soup.select_one(sel)
            if el:
                description = _clean(el.get_text('\n'))
                break

    how_to_apply_m = re.search(
        r'(?:How to Apply|To Apply|Send.*?CV|Application Process)[:\s]*([^\n]{10,300})',
        raw_text, re.I
    )
    how_to_apply = _clean(how_to_apply_m.group(1)) if how_to_apply_m else ''

    phone_m = PHONE_RE.search(raw_text)
    phone = _clean(phone_m.group(0)) if phone_m else ''

    closing_m = re.search(r'(?:Closing Date|Deadline)[:\s]*([^\n]{5,40})', raw_text, re.I)
    closing_date = _clean(closing_m.group(1)) if closing_m else ''

    return job_record({
        'title': title,
        'company': company,
        'location': location,
        'salary': salary,
        'job_type': job_type,
        'closing_date': closing_date,
        'apply_email': _find_email(description) or _find_email(raw_text),
        'phone': phone,
        'how_to_apply': how_to_apply,
        'url': url,
        'platform': 'jobmail',
        'description': description[:2000],
        'raw_text': raw_text[:3000],
    })


def _collect_links(keywords, max_pages=20):
    """
    Walk JobMail paginator — up to max_pages (default 20, ~600 listings).
    Tries keyword-specific URL first, falls back to IT category.
    """
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
            if pg == 1:
                url = start_url
            else:
                # JobMail pagination: /jobs/{cat}/page{N}?sort=latest
                base_path = start_url.split('?')[0]
                url = f'{base_path}/page{pg}?sort=latest'

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
    """
    Scrape up to `limit` JobMail listings across up to 20 pages.
    Default limit=500 is effectively uncapped for normal usage.
    """
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
