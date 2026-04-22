import re
import time
import requests
from bs4 import BeautifulSoup
from .async_http import parallel_fetch

BASE_URL  = 'https://www.jobmail.co.za'
START_URL = 'https://www.jobmail.co.za/jobs/it-computer?sort=latest'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0',
    'Accept-Language': 'en-ZA,en;q=0.9',
}
EMAIL_RE = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')
SKIP_EMAILS = {'noreply', 'no-reply', 'donotreply', 'support@jobmail', 'info@jobmail'}


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP_EMAILS):
            return m.group(0)
    return ''


def _clean(t):
    return re.sub(r'\s+', ' ', t or '').strip()


def _extract_id(url):
    m = re.search(r'-id-(\d+)', url)
    return m.group(1) if m else ''


def _parse_listing_page(html, keywords=None):
    soup = BeautifulSoup(html, 'html.parser')
    cards = []
    for a in soup.find_all('a', href=re.compile(r'/jobs/it-computer.+-id-\d+')):
        href = a.get('href', '')
        title = _clean(a.get_text())
        if not title or not href:
            continue
        parts = href.strip('/').split('/')
        location = parts[3].replace('-', ' ').title() if len(parts) > 3 else 'South Africa'
        full_url = href if href.startswith('http') else BASE_URL + href
        cards.append({'job_id': _extract_id(href), 'title': title, 'location': location, 'url': full_url})

    if keywords:
        kws = keywords.lower().split()
        cards = [c for c in cards if any(kw in c['title'].lower() for kw in kws)]
    return cards


def _scrape_detail(card_or_url):
    if isinstance(card_or_url, str):
        url = card_or_url
        card = {'title': '', 'location': 'South Africa', 'url': url, 'job_id': _extract_id(url)}
    else:
        card = card_or_url
        url = card['url']

    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(r.text, 'html.parser')
    text = soup.get_text(separator='\n')

    if not card.get('title'):
        title_el = soup.select_one('h1')
        card['title'] = _clean(title_el.get_text()) if title_el else ''
    if not card['title']:
        return None

    comp_m = re.search(r'(?:Recruiter|Company)[:\s]+([^\n]+)', text, re.I)
    company = _clean(comp_m.group(1)) if comp_m else ''

    sal_m = re.search(r'(R[\d ,]+(?:\s*[-–]\s*R[\d ,]+)?|Market Related|Negotiable)', text, re.I)

    desc_m = re.search(
        r'Apply Now\s*(.+?)(?:Apply Now|Create your FREE|Get notified|Sign in)',
        text, re.DOTALL | re.IGNORECASE
    )
    description = _clean(desc_m.group(1)) if desc_m else ''
    if not description:
        for sel in ['.job-description', '.description', 'article', '.content', 'main']:
            el = soup.select_one(sel)
            if el:
                description = _clean(el.get_text('\n'))
                break

    return {
        'title': card['title'],
        'company': company,
        'location': card.get('location', 'South Africa'),
        'description': description[:800],
        'url': url,
        'apply_email': _find_email(text),
        'platform': 'jobmail',
    }


def _collect_links(keywords, max_pages=3):
    session = requests.Session()
    session.headers.update(HEADERS)
    all_cards = []
    seen_ids = set()

    urls_to_try = []
    if keywords:
        q = keywords.strip().replace(' ', '-').lower()
        urls_to_try.append(f'{BASE_URL}/jobs/{q}?sort=latest')
    urls_to_try.append(START_URL)

    for start_url in urls_to_try:
        for pg in range(1, max_pages + 1):
            url = start_url if pg == 1 else f'{BASE_URL}/jobs/it-computer/page{pg}?sort=latest'
            try:
                r = session.get(url, timeout=20)
                r.raise_for_status()
                cards = _parse_listing_page(r.text, keywords)
                new_cards = [c for c in cards if c['job_id'] not in seen_ids]
                if not new_cards:
                    break
                for c in new_cards:
                    seen_ids.add(c['job_id'])
                all_cards.extend(new_cards)
                print(f'[JobMail] Page {pg}: {len(new_cards)} cards')
                time.sleep(0.3)
            except Exception as e:
                print(f'[JobMail] Page {pg} error: {e}')
                break
        if all_cards:
            break

    return all_cards


def scrape_jobmail(keywords=None, limit=30):
    cards = _collect_links(keywords, max_pages=3)
    if not cards:
        print('[JobMail] No jobs found')
        return []

    cards = cards[:limit]
    print(f'[JobMail] Fetching {len(cards)} detail pages in parallel...')
    jobs = parallel_fetch([c['url'] for c in cards], _scrape_detail, max_workers=10)
    jobs = [j for j in jobs if j and j.get('title')]
    print(f'[JobMail] {len(jobs)} jobs scraped')
    return jobs
