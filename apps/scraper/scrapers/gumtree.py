import re
import time
import requests
from bs4 import BeautifulSoup

BASE_URL  = 'https://www.gumtree.co.za'
CAT_CODE  = 'c9396'
CAT_SLUG  = 's-computing-it-cvs'
AD_SLUG   = 'a-computing-it-cvs'
JOBS_SLUG = 's-jobs'
JOBS_AD_SLUG = 'a-jobs'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0',
    'Accept-Language': 'en-ZA,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

EMAIL_RE = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')
SKIP_EMAILS = {'noreply', 'no-reply', 'donotreply', 'support@gumtree', 'info@gumtree'}

DELAY = 1.0


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
    all_links = []
    seen = set()

    if keywords:
        q = keywords.strip().replace(' ', '+')
        urls_to_try = [f'{BASE_URL}/results?q={q}&c={code}']
    else:
        urls_to_try = [_page_url(1, slug, code)]

    for start in urls_to_try:
        for pg in range(1, (max_pages or 5) + 1):
            url = start if pg == 1 else _page_url(pg, slug, code)
            try:
                r = requests.get(url, headers=HEADERS, timeout=20)
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
                print(f'[Gumtree] Page {pg}: {len(found)} links (total: {len(all_links)})')
                time.sleep(DELAY)
            except Exception as e:
                print(f'[Gumtree] Page {pg} error: {e}')
                break

        if all_links:
            break

    return all_links


def _scrape_ad(url, platform='gumtree'):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    text = soup.get_text(separator='\n')

    title_el = soup.select_one('h1')
    title = _clean(title_el.get_text()) if title_el else ''

    location = ''
    loc_el = soup.select_one('[class*="location"], [data-q="ad-location"]')
    if loc_el:
        location = _clean(loc_el.get_text())
    if not location:
        crumbs = soup.select('nav a, .breadcrumb a, ol li a')
        if len(crumbs) >= 2:
            location = _clean(crumbs[-2].get_text())
    if not location:
        loc_m = re.search(rf'/{re.escape(AD_SLUG)}/([^/]+)/', url)
        if loc_m:
            location = loc_m.group(1).replace('-', ' ').title()

    desc_el = soup.select_one(
        '[itemprop="description"], .description, [data-q="ad-description"], '
        'article .body, .ad-description, [class*="description"]'
    )
    description = _clean(desc_el.get_text('\n')) if desc_el else ''
    if not description:
        desc_m = re.search(r'Description\s*\n+(.+?)(?:\n{3,}|General Details|Contact|$)', text, re.DOTALL | re.I)
        description = _clean(desc_m.group(1)) if desc_m else ''

    company_el = soup.select_one('[class*="seller-name"], [data-q="seller-name"], .user-name, [class*="username"]')
    company = _clean(company_el.get_text()) if company_el else 'Via Gumtree'

    email = _find_email(text)

    prov_map = {
        'gauteng': 'Gauteng', 'western-cape': 'Western Cape', 'western cape': 'Western Cape',
        'kwazulu-natal': 'KwaZulu-Natal', 'eastern-cape': 'Eastern Cape',
        'limpopo': 'Limpopo', 'mpumalanga': 'Mpumalanga',
    }
    province = ''
    for key, val in prov_map.items():
        if key in url.lower() or key in text[:500].lower():
            province = val
            break

    return {
        'title': title,
        'company': company,
        'location': location or province or 'South Africa',
        'description': description[:800],
        'url': url,
        'apply_email': email,
        'platform': platform,
    }


def scrape_gumtree(keywords=None, limit=30):
    # Try jobs category first, fall back to IT CVs
    job_code = 'c9394'
    job_slug = 's-jobs'
    job_ad_slug = 'a-jobs'

    links = _collect_links(job_slug, job_ad_slug, job_code, keywords=keywords, max_pages=3)

    if not links:
        # Fall back to IT CVs category
        links = _collect_links(CAT_SLUG, AD_SLUG, CAT_CODE, keywords=keywords, max_pages=3)

    if not links:
        print('[Gumtree] No links found')
        return []

    jobs = []
    for i, url in enumerate(links[:limit], 1):
        try:
            job = _scrape_ad(url)
            if job['title']:
                jobs.append(job)
                print(f'[Gumtree] [{i}/{min(len(links), limit)}] {job["title"][:60]}')
        except Exception as e:
            print(f'[Gumtree] Error on {url}: {e}')
        time.sleep(DELAY)

    return jobs
