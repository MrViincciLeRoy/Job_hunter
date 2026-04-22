import re
import time
import requests
from bs4 import BeautifulSoup
from .async_http import parallel_fetch

BASE_URL  = 'https://www.careers24.com'
START_URL = 'https://www.careers24.com/jobs/se-it/rmt-incl/?sort=dateposted&ref=sbj'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0',
    'Accept-Language': 'en-ZA,en;q=0.9',
}
EMAIL_RE = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')
SKIP_EMAILS = {'noreply', 'no-reply', 'donotreply', 'support@careers24', 'info@careers24'}


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP_EMAILS):
            return m.group(0)
    return ''


def _clean(t):
    return re.sub(r'\s+', ' ', t or '').strip()


def _extract_job_id(url):
    m = re.search(r'/adverts/(\d+)-', url)
    return m.group(1) if m else ''


def _collect_links(keywords, max_pages=3):
    session = requests.Session()
    session.headers.update(HEADERS)
    all_links = []
    seen = set()

    urls_to_try = []
    if keywords:
        q = keywords.strip().replace(' ', '+')
        urls_to_try.append(f'{BASE_URL}/jobs/?k={q}&l=south+africa&sort=dateposted')
    urls_to_try.append(START_URL)

    for start_url in urls_to_try:
        for pg in range(1, max_pages + 1):
            url = start_url if pg == 1 else (
                f'{start_url}&startIndex={(pg - 1) * 20}' if '?' in start_url
                else f'{start_url.rstrip("/")}/pg{pg}/'
            )
            try:
                r = session.get(url, timeout=20)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, 'html.parser')
                found = []
                for a in soup.find_all('a', href=re.compile(r'/jobs/adverts/\d+')):
                    href = a['href']
                    full = href if href.startswith('http') else BASE_URL + href
                    key = full.split('?')[0]
                    if key not in seen and _extract_job_id(key):
                        seen.add(key)
                        found.append(key)
                if not found:
                    break
                all_links.extend(found)
                print(f'[Careers24] Page {pg}: {len(found)} links')
                time.sleep(0.5)
            except Exception as e:
                print(f'[Careers24] Page {pg} error: {e}')
                break
        if all_links:
            break

    return all_links


def _scrape_detail(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(r.text, 'html.parser')
    text = soup.get_text(separator='\n')

    title_el = soup.select_one('h1')
    title = _clean(title_el.get_text()) if title_el else ''
    if not title:
        return None

    emp_m = re.search(r'Employer[:\s]+(.+?)(?:\n|$)', text, re.I)
    company = _clean(emp_m.group(1)) if emp_m else ''

    loc_el = soup.select_one('a[href*="/jobs/lc-"]')
    location = _clean(loc_el.get_text()) if loc_el else 'South Africa'

    duties_m = re.search(
        r'(?:Duties\s+and\s+Responsibilities|Duties|Responsibilities)[:\s]*\n+(.+?)(?:\n{2,}|Minimum\s+Requirements|Requirements|Skills|Salary|$)',
        text, re.DOTALL | re.I
    )
    req_m = re.search(
        r'(?:Minimum\s+Requirements|Requirements|Qualifications)[:\s]*\n+(.+?)(?:\n{2,}|Knowledge|Skills|Salary|$)',
        text, re.DOTALL | re.I
    )
    description = ' '.join(filter(None, [
        _clean(duties_m.group(1)) if duties_m else '',
        _clean(req_m.group(1)) if req_m else '',
    ]))
    if not description:
        desc_el = soup.select_one('[class*="description"], article, main')
        description = _clean(desc_el.get_text('\n')) if desc_el else ''

    return {
        'title': title,
        'company': company,
        'location': location,
        'description': description[:800],
        'url': url,
        'apply_email': _find_email(text),
        'platform': 'careers24',
    }


def scrape_careers24(keywords=None, limit=30):
    links = _collect_links(keywords, max_pages=3)
    if not links:
        print('[Careers24] No links found')
        return []

    urls = links[:limit]
    print(f'[Careers24] Fetching {len(urls)} detail pages in parallel...')
    jobs = parallel_fetch(urls, _scrape_detail, max_workers=10)
    jobs = [j for j in jobs if j and j.get('title')]
    print(f'[Careers24] {len(jobs)} jobs scraped')
    return jobs
