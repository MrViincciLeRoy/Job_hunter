import re
import time
import requests
from bs4 import BeautifulSoup
from .async_http import parallel_fetch

BASE_URL  = 'https://www.gumtree.co.za'
CAT_CODE  = 'c9396'
CAT_SLUG  = 's-computing-it-cvs'
AD_SLUG   = 'a-computing-it-cvs'
JOBS_CODE = 'c9394'
JOBS_SLUG = 's-jobs'
JOBS_AD_SLUG = 'a-jobs'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0',
    'Accept-Language': 'en-ZA,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}
EMAIL_RE = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')
SKIP_EMAILS = {'noreply', 'no-reply', 'donotreply', 'support@gumtree', 'info@gumtree'}


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP_EMAILS):
            return m.group(0)
    return ''


def _clean(t):
    return re.sub(r'\s+', ' ', t or '').strip()


def _page_url(pg, slug, code):
    if pg == 1:
        return f'{BASE_URL}/{slug}/v1{code}p1'
    return f'{BASE_URL}/{slug}/page-{pg}/v1{code}p{pg}'


def _collect_links(slug, ad_slug, code, keywords=None, max_pages=3):
    session = requests.Session()
    session.headers.update(HEADERS)
    all_links = []
    seen = set()

    start_urls = ([f'{BASE_URL}/results?q={keywords.strip().replace(" ", "+")}&c={code}']
                  if keywords else [_page_url(1, slug, code)])

    for start in start_urls:
        for pg in range(1, max_pages + 1):
            url = start if pg == 1 else _page_url(pg, slug, code)
            try:
                r = session.get(url, timeout=20)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, 'html.parser')
                found = []
                for a in soup.find_all('a', href=re.compile(rf'/{re.escape(ad_slug)}/')):
                    href = a['href']
                    full = href if href.startswith('http') else BASE_URL + href
                    key = full.split('?')[0]
                    if key not in seen and key != BASE_URL + f'/{ad_slug}/':
                        seen.add(key)
                        found.append(key)
                if not found:
                    break
                all_links.extend(found)
                print(f'[Gumtree] Page {pg}: {len(found)} links')
                time.sleep(0.5)
            except Exception as e:
                print(f'[Gumtree] Page {pg} error: {e}')
                break
        if all_links:
            break

    return all_links


def _scrape_ad(url):
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

    loc_el = soup.select_one('[class*="location"], [data-q="ad-location"]')
    location = _clean(loc_el.get_text()) if loc_el else 'South Africa'

    desc_el = soup.select_one(
        '[itemprop="description"], .description, [data-q="ad-description"], '
        'article .body, [class*="description"]'
    )
    description = _clean(desc_el.get_text('\n')) if desc_el else ''

    company_el = soup.select_one('[class*="seller-name"], [data-q="seller-name"], .user-name')
    company = _clean(company_el.get_text()) if company_el else 'Via Gumtree'

    return {
        'title': title,
        'company': company,
        'location': location,
        'description': description[:800],
        'url': url,
        'apply_email': _find_email(text),
        'platform': 'gumtree',
    }


def scrape_gumtree(keywords=None, limit=30):
    links = _collect_links(JOBS_SLUG, JOBS_AD_SLUG, JOBS_CODE, keywords=keywords, max_pages=3)
    if not links:
        links = _collect_links(CAT_SLUG, AD_SLUG, CAT_CODE, keywords=keywords, max_pages=3)
    if not links:
        print('[Gumtree] No links found')
        return []

    urls = links[:limit]
    print(f'[Gumtree] Fetching {len(urls)} ads in parallel...')
    jobs = parallel_fetch(urls, _scrape_ad, max_workers=10)
    jobs = [j for j in jobs if j and j.get('title')]
    print(f'[Gumtree] {len(jobs)} jobs scraped')
    return jobs
