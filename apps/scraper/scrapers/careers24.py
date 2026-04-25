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

# Block any email whose domain matches these platform domains
SKIP_DOMAINS = {
    'careers24.com', 'pnet.co.za', 'careerjunction.co.za', 'jobmail.co.za',
    'gumtree.co.za', 'linkedin.com', 'indeed.com', 'glassdoor.com',
}
SKIP_PREFIXES = {'noreply', 'no-reply', 'donotreply', 'privacy', 'legal', 'support', 'info', 'admin', 'webmaster'}


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        local, domain = e.split('@', 1)
        if domain in SKIP_DOMAINS:
            continue
        if local in SKIP_PREFIXES:
            continue
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

    # Extract salary
    salary_m = re.search(r'(?:Salary|Remuneration|Package)[:\s]*([^\n]{3,80})', text, re.I)
    salary = _clean(salary_m.group(1)) if salary_m else 'Market Related'

    # Extract job type
    job_type_m = re.search(r'(?:Job Type|Contract Type|Employment Type)[:\s]*([^\n]{3,50})', text, re.I)
    job_type = _clean(job_type_m.group(1)) if job_type_m else ''

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

    # How to apply — look for apply instructions in text
    apply_m = re.search(r'(?:How to Apply|To Apply|Application Process|Send.*?CV|Apply.*?via)[:\s]*([^\n]{10,200})', text, re.I)
    how_to_apply = _clean(apply_m.group(1)) if apply_m else ''

    return {
        'title': title,
        'company': company,
        'location': location,
        'description': description[:1200],
        'url': url,
        'apply_email': _find_email(text),
        'platform': 'careers24',
        'salary': salary,
        'job_type': job_type,
        'how_to_apply': how_to_apply,
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
