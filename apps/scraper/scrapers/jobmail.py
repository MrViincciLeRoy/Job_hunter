import re
import time
import requests
from bs4 import BeautifulSoup

BASE_URL  = 'https://www.jobmail.co.za'
START_URL = 'https://www.jobmail.co.za/jobs/it-computer?sort=latest'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0',
    'Accept-Language': 'en-ZA,en;q=0.9',
}

EMAIL_RE = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')
SKIP_EMAILS = {'noreply', 'no-reply', 'donotreply', 'support@jobmail', 'info@jobmail'}

DELAY = 1.0


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

        container = a.find_parent(['div', 'li', 'article', 'section'])
        card_text = _clean(container.get_text(' | ')) if container else ''

        date_m = re.search(r'(\d{1,2}\s+\w+\s+\d{4})', card_text)
        sal_m = re.search(r'(R[\d ,]+(?:\s*[-–]\s*R[\d ,]+)?|Market Related|Negotiable)', card_text, re.I)
        src_m = re.search(r'(Recruiter|Company|Employer)', card_text, re.I)

        parts = href.strip('/').split('/')
        location = parts[3].replace('-', ' ').title() if len(parts) > 3 else ''
        category = parts[2].replace('-', ' ').title() if len(parts) > 2 else ''

        full_url = href if href.startswith('http') else BASE_URL + href

        cards.append({
            'job_id'     : _extract_id(href),
            'title'      : title,
            'category'   : category,
            'location'   : location or 'South Africa',
            'salary'     : sal_m.group(1).strip() if sal_m else '',
            'date_posted': date_m.group(1) if date_m else '',
            'source_type': src_m.group(1) if src_m else '',
            'source_url' : full_url,
            'company'    : '',
            'contract'   : '',
            'description': '',
            'requirements': '',
        })

    if keywords and cards:
        kws = keywords.lower().split()
        cards = [c for c in cards if any(kw in c['title'].lower() or kw in c['category'].lower() for kw in kws)]

    return cards


def _parse_detail_page(html, card):
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(separator='\n')

    comp_m = re.search(r'(?:Recruiter|Company)[:\s]+([^\n]+)', text, re.I)
    card['company'] = _clean(comp_m.group(1)) if comp_m else ''

    cont_m = re.search(r'(Full[\s-]?Time|Part[\s-]?Time|Contract|Permanent)', text, re.I)
    card['contract'] = cont_m.group(1) if cont_m else ''

    if not card['salary']:
        sal_m = re.search(r'(R[\d ,]+(?:\s*[-–]\s*R[\d ,]+)?|Market Related|Negotiable)', text, re.I)
        if sal_m:
            card['salary'] = sal_m.group(1).strip()

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

    card['description'] = description[:800]

    req_m = re.search(
        r'(?:Requirements?|Qualifications?|Minimum Requirements?)[:\s]+(.+?)(?:\n\n|Skills?:|Duties:|$)',
        description, re.DOTALL | re.IGNORECASE
    )
    card['requirements'] = _clean(req_m.group(1))[:500] if req_m else ''
    card['apply_email'] = _find_email(text)

    return card


def _collect_links_playwright(keywords, max_pages=3):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    all_cards = []
    seen_ids = set()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            ctx = browser.new_context(
                user_agent=HEADERS['User-Agent'],
                viewport={'width': 1280, 'height': 800}
            )
            list_page = ctx.new_page()

            for pg in range(1, (max_pages or 5) + 1):
                url = START_URL if pg == 1 else f'{BASE_URL}/jobs/it-computer/page{pg}?sort=latest'
                print(f'[JobMail/PW] Page {pg}: {url}')
                list_page.goto(url, wait_until='domcontentloaded', timeout=30000)
                time.sleep(3)

                html = list_page.content()
                cards = _parse_listing_page(html, keywords)
                new_cards = [c for c in cards if c['job_id'] not in seen_ids]
                print(f'[JobMail/PW] {len(new_cards)} new cards')

                if not new_cards:
                    break

                for c in new_cards:
                    seen_ids.add(c['job_id'])
                all_cards.extend(new_cards)

            list_page.close()

            detail_page = ctx.new_page()
            for i, job in enumerate(all_cards, 1):
                try:
                    detail_page.goto(job['source_url'], wait_until='domcontentloaded', timeout=25000)
                    time.sleep(2)
                    all_cards[i - 1] = _parse_detail_page(detail_page.content(), job)
                    print(f'[JobMail/PW] [{i}/{len(all_cards)}] {job["title"][:55]}')
                except Exception as e:
                    print(f'[JobMail/PW] Detail error: {e}')
                time.sleep(DELAY)

            browser.close()
    except Exception as e:
        print(f'[JobMail/PW] Error: {e}')
        return None

    return all_cards


def _collect_links_requests(keywords, max_pages=3):
    all_cards = []
    seen_ids = set()

    if keywords:
        q = keywords.strip().replace(' ', '-').lower()
        urls_to_try = [
            f'{BASE_URL}/jobs/{q}?sort=latest',
            f'{BASE_URL}/jobs/it-computer?sort=latest',
        ]
    else:
        urls_to_try = [START_URL]

    for start_url in urls_to_try:
        for pg in range(1, (max_pages or 5) + 1):
            url = start_url if pg == 1 else f'{BASE_URL}/jobs/it-computer/page{pg}?sort=latest'
            try:
                r = requests.get(url, headers=HEADERS, timeout=20)
                r.raise_for_status()
                cards = _parse_listing_page(r.text, keywords)
                new_cards = [c for c in cards if c['job_id'] not in seen_ids]
                if not new_cards:
                    break
                for c in new_cards:
                    seen_ids.add(c['job_id'])
                all_cards.extend(new_cards)
                print(f'[JobMail] Page {pg}: {len(new_cards)} cards')
                time.sleep(DELAY)
            except Exception as e:
                print(f'[JobMail] Page {pg} error: {e}')
                break

        if all_cards:
            break

    # Fetch detail pages
    for i, job in enumerate(all_cards, 1):
        try:
            r = requests.get(job['source_url'], headers=HEADERS, timeout=20)
            r.raise_for_status()
            all_cards[i - 1] = _parse_detail_page(r.text, job)
            print(f'[JobMail] [{i}/{len(all_cards)}] {job["title"][:55]}')
        except Exception as e:
            print(f'[JobMail] Detail error: {e}')
        time.sleep(DELAY)

    return all_cards


def scrape_jobmail(keywords=None, limit=30):
    cards = _collect_links_playwright(keywords, max_pages=3)
    if cards is None:
        print('[JobMail] Playwright unavailable, using requests')
        cards = _collect_links_requests(keywords, max_pages=3)

    if not cards:
        print('[JobMail] No jobs found')
        return []

    jobs = []
    for c in cards[:limit]:
        if not c.get('title'):
            continue
        jobs.append({
            'title'      : c['title'],
            'company'    : c['company'],
            'location'   : c['location'],
            'description': (c['description'] + ' ' + c['requirements']).strip()[:800],
            'url'        : c['source_url'],
            'apply_email': c.get('apply_email', ''),
            'platform'   : 'jobmail',
        })

    return jobs
