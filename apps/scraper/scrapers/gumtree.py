import re
import time
import random
import requests
from bs4 import BeautifulSoup
from .async_http import parallel_fetch
from utils.scraper_utils import random_headers, polite_delay, job_record

BASE_URL  = 'https://www.gumtree.co.za'
# Jobs category
JOBS_CODE = 'c9394'
JOBS_SLUG = 's-jobs'
JOBS_AD_SLUG = 'a-jobs'
# IT/Computing sub-category (fallback)
CAT_CODE  = 'c9396'
CAT_SLUG  = 's-computing-it-cvs'
AD_SLUG   = 'a-computing-it-cvs'

EMAIL_RE = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')
SKIP_EMAILS = {
    'noreply', 'no-reply', 'donotreply',
    'support@gumtree', 'info@gumtree', 'privacy@gumtree',
    'legal@gumtree', 'help@gumtree',
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


def _page_url(pg, slug, code):
    """Gumtree paginator: page 1 = /s-jobs/v1c9394p1, page N = /s-jobs/page-N/v1c9394pN"""
    if pg == 1:
        return f'{BASE_URL}/{slug}/v1{code}p1'
    return f'{BASE_URL}/{slug}/page-{pg}/v1{code}p{pg}'


def _collect_links(slug, ad_slug, code, keywords=None, max_pages=15):
    """
    Walk paginator pages and harvest all ad URLs.
    max_pages=15 → up to ~450 listings per category (Gumtree shows ~30/page).
    """
    session = requests.Session()
    session.headers.update(random_headers())
    all_links = []
    seen = set()
    consecutive_empty = 0

    start_urls = (
        [f'{BASE_URL}/results?q={keywords.strip().replace(" ", "+")}&c={code}']
        if keywords else
        [_page_url(1, slug, code)]
    )

    for start in start_urls:
        for pg in range(1, max_pages + 1):
            url = start if pg == 1 else _page_url(pg, slug, code)
            # Rotate headers every page to stay quiet
            session.headers.update(random_headers())
            try:
                r = session.get(url, timeout=25)
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
                    consecutive_empty += 1
                    if consecutive_empty >= 2:
                        print(f'[Gumtree] No new links at page {pg}, stopping')
                        break
                else:
                    consecutive_empty = 0

                all_links.extend(found)
                print(f'[Gumtree] Page {pg}: {len(found)} links (total: {len(all_links)})')

                # Polite inter-page delay: 1–3s
                time.sleep(random.uniform(1.0, 3.0))

            except Exception as e:
                print(f'[Gumtree] Page {pg} error: {e}')
                time.sleep(random.uniform(2.0, 5.0))
                break

        if all_links:
            break

    return all_links


def _scrape_ad(url):
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

    loc_el = soup.select_one('[class*="location"], [data-q="ad-location"], [class*="Location"]')
    location = _clean(loc_el.get_text()) if loc_el else ''
    if not location:
        loc_m = re.search(r'(?:Location|Area|City)[:\s]+([^\n]+)', raw_text, re.I)
        location = loc_m.group(1).strip() if loc_m else 'South Africa'

    desc_el = soup.select_one(
        '[itemprop="description"], .description, [data-q="ad-description"], '
        'article .body, [class*="description"], [class*="Description"]'
    )
    description = _clean(desc_el.get_text('\n')) if desc_el else ''
    if not description:
        description = raw_text[:1500]

    company_el = soup.select_one('[class*="seller-name"], [data-q="seller-name"], .user-name, [class*="SellerName"]')
    company = _clean(company_el.get_text()) if company_el else 'Via Gumtree'

    salary_m = re.search(r'(R\s?[\d\s,]+(?:\s?[-–]\s?R\s?[\d\s,]+)?|Market Related|Negotiable|CTC)', raw_text, re.I)
    salary = _clean(salary_m.group(0)) if salary_m else ''

    job_type_m = re.search(r'(permanent|contract|temporary|internship|learnership|part.time|full.time)', raw_text, re.I)
    job_type = job_type_m.group(0).title() if job_type_m else ''

    how_to_apply_m = re.search(r'(?:How to Apply|To Apply|Send.*?CV|email.*?CV)[:\s]*([^\n]{10,250})', raw_text, re.I)
    how_to_apply = _clean(how_to_apply_m.group(1)) if how_to_apply_m else ''

    phone_m = PHONE_RE.search(raw_text)
    phone = _clean(phone_m.group(0)) if phone_m else ''

    return job_record({
        'title': title,
        'company': company,
        'location': location,
        'salary': salary,
        'job_type': job_type,
        'apply_email': _find_email(description) or _find_email(raw_text),
        'phone': phone,
        'how_to_apply': how_to_apply,
        'url': url,
        'platform': 'gumtree',
        'description': description[:2000],
        'raw_text': raw_text[:3000],
    })


def scrape_gumtree(keywords=None, limit=500):
    """
    Scrape up to `limit` Gumtree job ads across up to 15 pages.
    Default limit=500 is effectively uncapped for normal usage.
    Falls back from IT sub-category to general jobs category.
    """
    # Try general jobs category first, IT as fallback
    links = _collect_links(JOBS_SLUG, JOBS_AD_SLUG, JOBS_CODE, keywords=keywords, max_pages=15)
    if not links:
        print('[Gumtree] No links from jobs category, trying IT sub-category...')
        links = _collect_links(CAT_SLUG, AD_SLUG, CAT_CODE, keywords=keywords, max_pages=15)

    if not links:
        print('[Gumtree] No links found at all')
        return []

    urls = links[:limit]
    print(f'[Gumtree] Fetching {len(urls)} ads in parallel (workers=14)...')
    jobs = parallel_fetch(urls, _scrape_ad, max_workers=14)
    jobs = [j for j in jobs if j and j.get('title')]
    print(f'[Gumtree] {len(jobs)} jobs scraped')
    return jobs
