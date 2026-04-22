import re
import time
import requests
from bs4 import BeautifulSoup
from .async_http import parallel_fetch

BASE_URL = 'https://www.careerjunction.co.za'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-ZA,en;q=0.9',
}
IT_SEARCH_URL = 'https://www.careerjunction.co.za/jobs/results?Location=1&SortBy=Relevance&rbcat=16&lr=0'
GENERAL_SEARCH_URL = 'https://www.careerjunction.co.za/jobs/results?Location=1&SortBy=Relevance&lr=0'
EMAIL_RE = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')
SKIP_EMAILS = {'noreply', 'no-reply', 'donotreply', 'info@careerjunction', 'support@careerjunction', 'privacy', 'legal'}


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP_EMAILS):
            return m.group(0)
    return ''


def _get_listing_links(search_url, per_page=100, max_pages=5):
    links = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for page in range(1, max_pages + 1):
        url = f'{search_url}&PerPage={per_page}&Page={page}'
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')
            found = []
            for a in soup.select('a[href*="-job-"]'):
                href = a['href']
                if href.endswith('.aspx') and '-job-' in href:
                    full = href if href.startswith('http') else BASE_URL + href
                    if full not in links:
                        found.append(full)
            if not found:
                break
            links.extend(found)
            print(f'[CJ] Page {page}: {len(found)} jobs (total: {len(links)})')
            if len(found) < per_page:
                break
        except Exception as e:
            print(f'[CJ] Listing page {page} error: {e}')
            break

    return list(dict.fromkeys(links))


def _scrape_job(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        return None

    soup = BeautifulSoup(r.text, 'html.parser')

    def text(selector, default=''):
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else default

    title = text('h1')
    if not title:
        return None

    company = text('h2 a') or text('h2')
    meta_items = [el.get_text(strip=True) for el in soup.select('ul.job-summary li, .job-details li, section ul li')]

    salary = job_type = level = location = ''
    for item in meta_items:
        item_l = item.lower()
        if 'undisclosed' in item_l or item.startswith('R ') or 'market related' in item_l:
            salary = item
        elif any(t in item_l for t in ['permanent', 'contract', 'internship']):
            job_type = item
        elif not location and len(item) < 50 and re.match(r'^[A-Z][a-z]', item):
            location = item

    desc_el = soup.select_one('.job-description, article, .about-position, section.description')
    description = desc_el.get_text(separator='\n', strip=True) if desc_el else ''
    if not description:
        all_text = soup.get_text(separator='\n')
        m = re.search(r'About the position(.+?)(?:Apply Now|Desired Skills|$)', all_text, re.DOTALL | re.IGNORECASE)
        description = m.group(1).strip() if m else ''

    email = _find_email(description) or _find_email(soup.get_text())

    return {
        'title': title,
        'company': company,
        'location': location or 'South Africa',
        'description': description[:800],
        'url': url,
        'apply_email': email,
        'platform': 'careerjunction',
    }


def _scrape_job_it(url):
    job = _scrape_job(url)
    if job:
        job['platform'] = 'careerjunction_it'
    return job


def scrape_careerjunction(keywords=None, limit=50):
    if keywords:
        q = keywords.strip().replace(' ', '+')
        search_url = f'{BASE_URL}/jobs/results?Keywords={q}&Location=1&SortBy=Relevance&lr=0'
    else:
        search_url = GENERAL_SEARCH_URL

    links = _get_listing_links(search_url, per_page=100, max_pages=3)
    if not links:
        print('[CJ] No links, falling back to IT category')
        links = _get_listing_links(IT_SEARCH_URL, per_page=100, max_pages=3)

    urls = links[:limit]
    print(f'[CJ] Fetching {len(urls)} detail pages in parallel...')
    jobs = parallel_fetch(urls, _scrape_job, max_workers=10)
    jobs = [j for j in jobs if j and j.get('title')]
    print(f'[CJ] {len(jobs)} jobs scraped')
    return jobs


def scrape_careerjunction_it(keywords=None, limit=50):
    if keywords:
        q = keywords.strip().replace(' ', '+')
        search_url = f'{BASE_URL}/jobs/results?Keywords={q}&Location=1&SortBy=Relevance&rbcat=16&lr=0'
    else:
        search_url = IT_SEARCH_URL

    links = _get_listing_links(search_url, per_page=100, max_pages=3)
    urls = links[:limit]
    print(f'[CJ-IT] Fetching {len(urls)} detail pages in parallel...')
    jobs = parallel_fetch(urls, _scrape_job_it, max_workers=10)
    jobs = [j for j in jobs if j and j.get('title')]
    print(f'[CJ-IT] {len(jobs)} jobs scraped')
    return jobs
