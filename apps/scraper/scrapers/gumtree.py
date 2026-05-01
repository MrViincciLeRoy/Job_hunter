import re
import time
import random
import requests
from bs4 import BeautifulSoup
from .async_http import parallel_fetch
from utils.scraper_utils import (
    random_headers, polite_delay, job_record,
    extract_email_priority, extract_closing_date, is_hire_me_post,
)

BASE_URL  = 'https://www.gumtree.co.za'
JOBS_CODE = 'c9394'
JOBS_SLUG = 's-jobs'
JOBS_AD_SLUG = 'a-jobs'
CAT_CODE  = 'c9396'
CAT_SLUG  = 's-computing-it-cvs'
AD_SLUG   = 'a-computing-it-cvs'

PHONE_RE = re.compile(r'(\+27|0)[0-9()\s-]{8,14}')

# Skip entire category pages that are CV/hire-me sections
_SKIP_CATEGORY_SLUGS = re.compile(
    r'/(?:s-computing-it-cvs|s-cvs|s-looking-for-work|s-domestic-workers-looking)/',
    re.IGNORECASE,
)


def _clean(t):
    return re.sub(r'\s+', ' ', t or '').strip()


def _page_url(pg, slug, code):
    if pg == 1:
        return f'{BASE_URL}/{slug}/v1{code}p1'
    return f'{BASE_URL}/{slug}/page-{pg}/v1{code}p{pg}'


def _collect_links(slug, ad_slug, code, keywords=None, max_pages=15):
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
            session.headers.update(random_headers())
            try:
                r = session.get(url, timeout=25)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, 'html.parser')
                found = []
                for a in soup.find_all('a', href=re.compile(rf'/{re.escape(ad_slug)}/')):
                    href = a['href']
                    if _SKIP_CATEGORY_SLUGS.search(href):
                        continue
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

    # Pull description early — needed for hire-me check
    desc_el = soup.select_one(
        '[itemprop="description"], .description, [data-q="ad-description"], '
        'article .body, [class*="description"], [class*="Description"]'
    )
    description = _clean(desc_el.get_text('\n')) if desc_el else ''
    if not description:
        description = raw_text[:2000]

    # Filter: skip hire-me / CV posts
    if is_hire_me_post(title, description):
        print(f'[Gumtree] Skipping hire-me post: {title[:60]}')
        return None

    loc_el = soup.select_one(
        '[class*="location"], [data-q="ad-location"], [class*="Location"], '
        '[itemprop="addressLocality"]'
    )
    location = _clean(loc_el.get_text()) if loc_el else ''
    if not location:
        loc_m = re.search(r'(?:Location|Area|City|Province)[:\s]+([^\n]+)', raw_text, re.I)
        location = loc_m.group(1).strip() if loc_m else 'South Africa'

    company_el = soup.select_one(
        '[class*="seller-name"], [data-q="seller-name"], .user-name, '
        '[class*="SellerName"], [itemprop="name"]'
    )
    company = _clean(company_el.get_text()) if company_el else 'Via Gumtree'

    salary_m = re.search(
        r'(R\s?[\d\s,]+(?:\s?[-–]\s?R\s?[\d\s,]+)?|Market\s+Related|Negotiable|CTC)',
        raw_text, re.I
    )
    salary = _clean(salary_m.group(0)) if salary_m else ''

    job_type_m = re.search(
        r'\b(permanent|contract|temporary|internship|learnership|part[- ]time|full[- ]time)\b',
        raw_text, re.I
    )
    job_type = job_type_m.group(0).title() if job_type_m else ''

    how_to_apply_m = re.search(
        r'(?:How\s+to\s+Apply|To\s+Apply|Send.*?CV|email.*?CV|Forward.*?CV|'
        r'Applications?\s+to|Apply\s+(?:via|by|to))[:\s]*([^\n]{10,300})',
        raw_text, re.I
    )
    how_to_apply = _clean(how_to_apply_m.group(1)) if how_to_apply_m else ''

    apply_email = extract_email_priority(
        how_to_apply=how_to_apply,
        description=description,
        raw_text=raw_text,
    )

    closing_date = extract_closing_date(raw_text)

    phone_m = PHONE_RE.search(raw_text)
    phone = _clean(phone_m.group(0)) if phone_m else ''

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
        'platform':     'gumtree',
        'description':  description[:2000],
        'raw_text':     raw_text[:3000],
    })


def scrape_gumtree(keywords=None, limit=500):
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
    print(f'[Gumtree] {len(jobs)} valid job ads scraped (hire-me posts filtered)')
    return jobs
