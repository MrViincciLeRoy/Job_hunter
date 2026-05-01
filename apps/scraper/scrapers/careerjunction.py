import re
import requests
from bs4 import BeautifulSoup
from .async_http import parallel_fetch
from utils.scraper_utils import (
    random_headers, polite_delay, page_delay, job_record,
    extract_email_priority, extract_closing_date,
)

BASE_URL          = 'https://www.careerjunction.co.za'
IT_SEARCH_URL      = f'{BASE_URL}/jobs/results?Location=1&SortBy=Relevance&rbcat=16&lr=0'
GENERAL_SEARCH_URL = f'{BASE_URL}/jobs/results?Location=1&SortBy=Relevance&lr=0'
PHONE_RE = re.compile(r'(\+27|0)[0-9()\s-]{8,14}')


def _get_listing_links(search_url, per_page=100, max_pages=20):
    links = []
    seen = set()
    session = requests.Session()

    for page in range(1, max_pages + 1):
        session.headers.update(random_headers())
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
                    if full not in seen:
                        seen.add(full)
                        found.append(full)
            if not found:
                print(f'[CJ] No more results at page {page}, stopping')
                break
            links.extend(found)
            print(f'[CJ] Page {page}: {len(found)} jobs (total: {len(links)})')
            if len(found) < 10:
                break
            page_delay()
        except Exception as e:
            print(f'[CJ] Page {page} error: {e}')
            break

    return links


def _scrape_job(url):
    try:
        r = requests.get(url, headers=random_headers(), timeout=20)
        r.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(r.text, 'html.parser')
    raw_text = soup.get_text(separator='\n', strip=True)

    def text(selector, default=''):
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else default

    title = text('h1')
    if not title:
        return None

    company = text('h2 a') or text('h2')

    meta_items = [
        el.get_text(strip=True)
        for el in soup.select('ul.job-summary li, .job-details li, section ul li')
    ]

    salary = job_type = location = ''
    for item in meta_items:
        item_l = item.lower()
        if any(x in item_l for x in ['undisclosed', 'market related']) or re.match(r'R\s?[\d,]+', item):
            salary = item
        elif any(t in item_l for t in ['permanent', 'contract', 'temporary', 'internship',
                                        'learnership', 'part-time', 'full-time']):
            job_type = item
        elif not location and len(item) < 60 and re.match(r'^[A-Z][a-z]', item):
            location = item

    if not location:
        loc_m = re.search(r'(?:Location|City)[:\s]+([^\n]+)', raw_text, re.I)
        location = loc_m.group(1).strip() if loc_m else 'South Africa'

    desc_el = soup.select_one(
        '.job-description, article, .about-position, section.description, '
        '[class*="description"], [class*="Description"]'
    )
    description = desc_el.get_text(separator='\n', strip=True) if desc_el else ''
    if not description:
        m = re.search(r'About the position(.+?)(?:Apply Now|Desired Skills|$)', raw_text, re.DOTALL | re.I)
        description = m.group(1).strip() if m else ''

    req_m = re.search(
        r'(?:Minimum\s+Requirements?|Requirements?|Qualifications?)[:\s]*\n+(.*?)(?:\n{2,}|Duties|Skills|$)',
        raw_text, re.DOTALL | re.I
    )
    requirements = req_m.group(1).strip()[:600] if req_m else ''

    duties_m = re.search(
        r'(?:Duties\s+(?:and\s+)?Responsibilities|Responsibilities|Key\s+Duties)[:\s]*\n+(.*?)(?:\n{2,}|Requirements?|Skills|$)',
        raw_text, re.DOTALL | re.I
    )
    duties = duties_m.group(1).strip()[:600] if duties_m else ''

    if len(description) < 300 and (requirements or duties):
        description = ' | '.join(filter(None, [description, requirements, duties]))

    how_to_apply_m = re.search(
        r'(?:How\s+to\s+Apply|To\s+Apply|Application\s+Process|'
        r'Forward.*?CV|Send.*?CV|email.*?CV)[:\s]*([^\n]{10,300})',
        raw_text, re.I
    )
    how_to_apply = how_to_apply_m.group(1).strip() if how_to_apply_m else ''

    apply_email = extract_email_priority(
        how_to_apply=how_to_apply,
        description=description,
        raw_text=raw_text,
    )

    closing_date = extract_closing_date(raw_text)

    phone_m = PHONE_RE.search(raw_text)
    phone = phone_m.group(0).strip() if phone_m else ''

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
        'platform':     'careerjunction',
        'description':  description[:2000],
        'raw_text':     raw_text[:3000],
    })


def _scrape_job_it(url):
    job = _scrape_job(url)
    if job:
        job['platform'] = 'careerjunction_it'
    return job


def scrape_careerjunction(keywords=None, limit=500):
    if keywords:
        q = keywords.strip().replace(' ', '+')
        search_url = f'{BASE_URL}/jobs/results?Keywords={q}&Location=1&SortBy=Relevance&lr=0'
    else:
        search_url = GENERAL_SEARCH_URL

    links = _get_listing_links(search_url, per_page=100, max_pages=20)
    if not links:
        print('[CJ] No links, falling back to IT category')
        links = _get_listing_links(IT_SEARCH_URL, per_page=100, max_pages=20)

    print(f'[CJ] Fetching {len(links)} detail pages in parallel...')
    jobs = parallel_fetch(links[:limit], _scrape_job, max_workers=12)
    jobs = [j for j in jobs if j and j.get('title')]
    print(f'[CJ] {len(jobs)} jobs scraped')
    return jobs


def scrape_careerjunction_it(keywords=None, limit=500):
    if keywords:
        q = keywords.strip().replace(' ', '+')
        search_url = f'{BASE_URL}/jobs/results?Keywords={q}&Location=1&SortBy=Relevance&rbcat=16&lr=0'
    else:
        search_url = IT_SEARCH_URL

    links = _get_listing_links(search_url, per_page=100, max_pages=20)
    print(f'[CJ-IT] Fetching {len(links)} detail pages in parallel...')
    jobs = parallel_fetch(links[:limit], _scrape_job_it, max_workers=12)
    jobs = [j for j in jobs if j and j.get('title')]
    print(f'[CJ-IT] {len(jobs)} jobs scraped')
    return jobs
