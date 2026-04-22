import re
import time
import requests
from bs4 import BeautifulSoup

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

DELAY = 1.0


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP_EMAILS):
            return m.group(0)
    return ''


def _get_listing_links(search_url, per_page=100, max_pages=5):
    links = []
    for page in range(1, (max_pages or 99) + 1):
        url = f'{search_url}&PerPage={per_page}&Page={page}'
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
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

            time.sleep(DELAY)
        except Exception as e:
            print(f'[CJ] Listing page {page} error: {e}')
            break

    return list(dict.fromkeys(links))


def _scrape_job(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')

    def text(selector, default=''):
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else default

    title = text('h1')
    company = text('h2 a') or text('h2')

    meta_items = [el.get_text(strip=True) for el in soup.select('ul.job-summary li, .job-details li, section ul li')]

    salary = job_type = level = location = posted = job_id = ref = ''
    for item in meta_items:
        item_l = item.lower()
        if 'undisclosed' in item_l or item.startswith('R ') or 'market related' in item_l:
            salary = item
        elif any(t in item_l for t in ['permanent', 'contract', 'internship']):
            job_type = item
            for lvl in ['Senior', 'Intermediate', 'Junior', 'Specialist', 'Management']:
                if lvl.lower() in item_l:
                    level = lvl
                    break
        elif 'posted' in item_l:
            posted = re.sub(r'posted\s*', '', item, flags=re.IGNORECASE).strip()
        elif 'job ' in item_l and '-' in item:
            m = re.search(r'Job\s+(\d+)', item, re.IGNORECASE)
            if m: job_id = m.group(1)
            m = re.search(r'Ref\s+(\S+)', item, re.IGNORECASE)
            if m: ref = m.group(1)
        elif not location and len(item) < 50 and re.match(r'^[A-Z][a-z]', item):
            location = item

    desc_el = soup.select_one('.job-description, article, .about-position, section.description')
    description = desc_el.get_text(separator='\n', strip=True) if desc_el else ''
    if not description:
        all_text = soup.get_text(separator='\n')
        m = re.search(r'About the position(.+?)(?:Apply Now|Desired Skills|$)', all_text, re.DOTALL | re.IGNORECASE)
        description = m.group(1).strip() if m else ''

    skills_els = [el.get_text(strip=True) for el in soup.select('ul.desired-skills li, .skills li, .tags li')]
    if not skills_els:
        m = re.search(r'Desired Skills[:\s]+((?:\*\s*.+\n?)+)', soup.get_text(), re.IGNORECASE)
        if m:
            skills_els = [s.strip('* ').strip() for s in m.group(1).splitlines() if s.strip()]

    apply_link = ''
    for a in soup.select('a[href*="/apply/"]'):
        apply_link = a['href'] if a['href'].startswith('http') else BASE_URL + a['href']
        break

    email = _find_email(description) or _find_email(soup.get_text())

    return {
        'title': title,
        'company': company,
        'location': location or 'South Africa',
        'description': description[:800],
        'url': url,
        'apply_email': email,
        'platform': 'careerjunction',
        '_salary': salary,
        '_job_type': job_type,
        '_level': level,
        '_posted': posted,
        '_skills': ', '.join(skills_els),
        '_apply_url': apply_link,
        '_job_id': job_id,
        '_ref': ref,
    }


def scrape_careerjunction(keywords=None, limit=50):
    if keywords:
        q = keywords.strip().replace(' ', '+')
        search_url = f'{BASE_URL}/jobs/results?Keywords={q}&Location=1&SortBy=Relevance&lr=0'
    else:
        search_url = GENERAL_SEARCH_URL

    links = _get_listing_links(search_url, per_page=100, max_pages=3)

    if not links:
        print('[CJ] No links found, falling back to IT category')
        links = _get_listing_links(IT_SEARCH_URL, per_page=100, max_pages=3)

    jobs = []
    for i, url in enumerate(links[:limit], 1):
        try:
            job = _scrape_job(url)
            if job['title']:
                jobs.append(job)
                print(f'[CJ] [{i}/{min(len(links), limit)}] {job["title"][:60]} @ {job["company"]}')
        except Exception as e:
            print(f'[CJ] Error on {url}: {e}')
        time.sleep(DELAY)

    return jobs


def scrape_careerjunction_it(keywords=None, limit=50):
    if keywords:
        q = keywords.strip().replace(' ', '+')
        search_url = f'{BASE_URL}/jobs/results?Keywords={q}&Location=1&SortBy=Relevance&rbcat=16&lr=0'
    else:
        search_url = IT_SEARCH_URL

    links = _get_listing_links(search_url, per_page=100, max_pages=3)
    jobs = []
    for i, url in enumerate(links[:limit], 1):
        try:
            job = _scrape_job(url)
            job['platform'] = 'careerjunction_it'
            if job['title']:
                jobs.append(job)
                print(f'[CJ-IT] [{i}/{min(len(links), limit)}] {job["title"][:60]}')
        except Exception as e:
            print(f'[CJ-IT] Error on {url}: {e}')
        time.sleep(DELAY)

    return jobs
