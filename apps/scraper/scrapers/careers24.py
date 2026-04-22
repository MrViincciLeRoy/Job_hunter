import re
import time
import requests
from bs4 import BeautifulSoup

BASE_URL  = 'https://www.careers24.com'
START_URL = 'https://www.careers24.com/jobs/se-it/rmt-incl/?sort=dateposted&ref=sbj'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0',
    'Accept-Language': 'en-ZA,en;q=0.9',
}

EMAIL_RE = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')
SKIP_EMAILS = {'noreply', 'no-reply', 'donotreply', 'support@careers24', 'info@careers24'}

DELAY = 1.0


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


def _get_links_from_html(html, seen):
    soup = BeautifulSoup(html, 'html.parser')
    found = []
    for a in soup.find_all('a', href=re.compile(r'/jobs/adverts/\d+')):
        href = a['href']
        full = href if href.startswith('http') else BASE_URL + href
        key = full.split('?')[0]
        if key not in seen and _extract_job_id(key):
            seen.add(key)
            found.append(key)
    return found


def _collect_links_requests(keywords, max_pages=3):
    """Requests-based fallback — works when Playwright isn't available."""
    all_links = []
    seen = set()

    if keywords:
        q = keywords.strip().replace(' ', '+')
        urls_to_try = [
            f'{BASE_URL}/jobs/?k={q}&l=south+africa&sort=dateposted',
            f'{BASE_URL}/jobs/se-it/rmt-incl/?sort=dateposted',
        ]
    else:
        urls_to_try = [START_URL]

    for start_url in urls_to_try:
        for pg in range(1, (max_pages or 5) + 1):
            if pg == 1:
                url = start_url
            else:
                # Careers24 pagination patterns
                if '?' in start_url:
                    url = f'{start_url}&startIndex={(pg - 1) * 20}'
                else:
                    base_path = start_url.rstrip('/')
                    url = f'{base_path}/pg{pg}/'

            try:
                r = requests.get(url, headers=HEADERS, timeout=20)
                r.raise_for_status()
                found = _get_links_from_html(r.text, seen)
                if not found:
                    break
                all_links.extend(found)
                print(f'[Careers24] Page {pg}: {len(found)} links (total: {len(all_links)})')
                time.sleep(DELAY)
            except Exception as e:
                print(f'[Careers24] Page {pg} error: {e}')
                break

        if all_links:
            break

    return all_links


def _collect_links_playwright(keywords, max_pages=3):
    """Playwright-based collector — handles JS-rendered pagination."""
    try:
        import asyncio
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    all_links = []
    seen = set()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            ctx = browser.new_context(user_agent=HEADERS['User-Agent'], viewport={'width': 1280, 'height': 900})
            page = ctx.new_page()
            page.route('**/*.{png,jpg,gif,svg,woff,woff2,ttf,ico}', lambda r: r.abort())

            if keywords:
                q = keywords.strip().replace(' ', '+')
                start = f'{BASE_URL}/jobs/?k={q}&l=south+africa&sort=dateposted'
            else:
                start = START_URL

            print(f'[Careers24/PW] Page 1: {start}')
            page.goto(start, wait_until='networkidle', timeout=40000)
            time.sleep(3)

            pg = 1
            while True:
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                time.sleep(2)

                html = page.content()
                found = _get_links_from_html(html, seen)
                print(f'[Careers24/PW] Page {pg}: {len(found)} links')
                all_links.extend(found)

                if not found or (max_pages and pg >= max_pages):
                    break

                # Try navigating to next page
                navigated = False
                soup = BeautifulSoup(html, 'html.parser')
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    txt = a.get_text(strip=True)
                    if href in ('#', '') or href.startswith('javascript'):
                        continue
                    if (txt == str(pg + 1) or f'pg{pg + 1}' in href
                            or f'page={pg + 1}' in href or f'startIndex={pg * 20}' in href):
                        next_url = href if href.startswith('http') else BASE_URL + href
                        page.goto(next_url, wait_until='networkidle', timeout=40000)
                        time.sleep(3)
                        navigated = True
                        pg += 1
                        break

                if not navigated:
                    for sel in [
                        f'[aria-label="Page {pg + 1}"]',
                        'a[aria-label*="Next" i]',
                        '[class*="next"]:not([class*="prev"])',
                        '.pagination li:last-child a',
                    ]:
                        try:
                            el = page.query_selector(sel)
                            if el and el.is_visible():
                                old_url = page.url
                                el.click()
                                time.sleep(3)
                                if page.url != old_url:
                                    navigated = True
                                    pg += 1
                                    break
                        except Exception:
                            continue

                if not navigated:
                    break

            browser.close()
    except Exception as e:
        print(f'[Careers24/PW] Error: {e}')
        return None

    return all_links


def _scrape_detail(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    text = soup.get_text(separator='\n')

    title_el = soup.select_one('h1')
    title = _clean(title_el.get_text()) if title_el else ''

    emp_m = re.search(r'Employer[:\s]+(.+?)(?:\n|$)', text, re.I)
    company = _clean(emp_m.group(1)) if emp_m else ''

    loc_el = soup.select_one('a[href*="/jobs/lc-"]')
    location = _clean(loc_el.get_text()) if loc_el else 'South Africa'

    sal_m = re.search(
        r'Salary[:\s]+(R[\d ,]+(?:\s*[-–]\s*R[\d ,]+)?(?:\s*(?:per|p/)\w+)?|Market[\s-]?[Rr]elated|Negotiable|CTC[^\n]*)',
        text, re.I
    )
    salary = _clean(sal_m.group(1)) if sal_m else ''

    jtype_m = re.search(r'Job\s+Type[:\s]+(Permanent|Contract|Temporary|Part-?Time|Internship)', text, re.I)
    job_type = jtype_m.group(1) if jtype_m else ''

    date_m = re.search(r'Posted[:\s]+(\d{1,2}\s+\w+\s+\d{4})', text, re.I)
    date_posted = _clean(date_m.group(1)) if date_m else ''

    duties_m = re.search(
        r'(?:Duties\s+and\s+Responsibilities|Duties|Responsibilities)[:\s]*\n+(.+?)(?:\n{2,}|Minimum\s+Requirements|Requirements|Skills|Salary|$)',
        text, re.DOTALL | re.I
    )
    duties = _clean(duties_m.group(1)) if duties_m else ''

    req_m = re.search(
        r'(?:Minimum\s+Requirements|Requirements|Qualifications)[:\s]*\n+(.+?)(?:\n{2,}|Knowledge|Skills|Salary|Benefits|$)',
        text, re.DOTALL | re.I
    )
    requirements = _clean(req_m.group(1)) if req_m else ''

    description = ' '.join(filter(None, [duties, requirements]))
    if not description:
        desc_el = soup.select_one('[class*="description"], article, main')
        description = _clean(desc_el.get_text('\n')) if desc_el else ''

    email = _find_email(text)

    ref_m = re.search(r'Reference[:\s]+(\S+)', text, re.I)

    return {
        'title': title,
        'company': company,
        'location': location,
        'description': description[:800],
        'url': url,
        'apply_email': email,
        'platform': 'careers24',
        '_salary': salary,
        '_job_type': job_type,
        '_date_posted': date_posted,
        '_ref': ref_m.group(1) if ref_m else '',
        '_job_id': _extract_job_id(url),
    }


def scrape_careers24(keywords=None, limit=30):
    # Try Playwright first, fall back to requests
    links = _collect_links_playwright(keywords, max_pages=3)
    if links is None:
        print('[Careers24] Playwright unavailable, using requests')
        links = _collect_links_requests(keywords, max_pages=3)

    if not links:
        print('[Careers24] No links found')
        return []

    jobs = []
    for i, url in enumerate(links[:limit], 1):
        try:
            job = _scrape_detail(url)
            if job['title']:
                jobs.append(job)
                print(f'[Careers24] [{i}/{min(len(links), limit)}] {job["title"][:60]} @ {job["company"]}')
        except Exception as e:
            print(f'[Careers24] Error on {url}: {e}')
        time.sleep(DELAY)

    return jobs
