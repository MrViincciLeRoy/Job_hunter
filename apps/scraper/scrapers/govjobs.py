from apps.scraper.scrapers.dpsa import scrape_dpsa  # noqa: F401

import re
import time
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlencode
from utils.scraper_utils import random_headers, job_record

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
SKIP_EMAILS = {
    "noreply", "no-reply", "donotreply", "webmaster", "admin",
    "privacy", "legal", "info@dpsa", "help", "support",
}
PHONE_RE = re.compile(r"(\+27|0)[0-9()\s-]{8,14}")

GOV_JOB_TYPES = [
    ('internship',  ['internship', ' intern ']),
    ('learnership', ['learnership']),
    ('scholarship', ['scholarship', 'bursary']),
    ('graduate',    ['graduate programme', 'graduate program']),
    ('entry level', ['entry level', 'entry-level']),
]


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP_EMAILS):
            return m.group(0)
    return ""


def _find_phone(text):
    m = PHONE_RE.search(text)
    return m.group(0).strip() if m else ""


def _clean(t):
    return re.sub(r'\s+', ' ', t or '').strip()


def _detect_job_type(title, text=''):
    combined = (title + ' ' + text).lower()
    for jtype, terms in GOV_JOB_TYPES:
        if any(t in combined for t in terms):
            return jtype
    return 'Government'


def _extract_docs(text):
    t = text.lower()
    docs = []
    if 'z83' in t:
        docs.append('Z83 form')
    if 'certified cop' in t:
        docs.append('Certified copies of qualifications & ID')
    if 'curriculum vitae' in t or re.search(r'\bcv\b', t):
        docs.append('CV')
    if 'driver' in t and 'licen' in t:
        docs.append("Driver's licence")
    if 'medical certificate' in t:
        docs.append('Medical certificate')
    if 'police clearance' in t:
        docs.append('Police clearance')
    if 'security clearance' in t:
        docs.append('Security clearance')
    return ', '.join(docs) if docs else ''


def _extract_salary(text):
    m = re.search(r'(R\s?[\d\s,]+(?:\s?[-–]\s?R\s?[\d\s,]+)?|salary level\s*\d+)', text, re.I)
    return _clean(m.group(0)) if m else ''


def _extract_closing(text):
    m = re.search(r'(?:closing date|deadline)[:\s]+([^\n]{5,40})', text, re.I)
    return _clean(m.group(1)) if m else ''


# ─── SAYouth ──────────────────────────────────────────────────────────────────

def scrape_sayouth(keywords=None, limit=200):
    """
    Scrape SAYouth.mobi — paginate up to 10 pages (~200 listings).
    """
    base = "https://sayouth.mobi"
    jobs = []
    seen = set()

    search_paths = []
    if keywords:
        search_paths.append(f"/Jobs?search={keywords.replace(' ', '+')}")
    search_paths.append("/Jobs")
    # Also hit category pages for broader coverage
    search_paths += ["/Jobs?category=IT", "/Jobs?category=Government", "/Jobs?category=Internship"]

    session = requests.Session()

    for path in search_paths:
        for pg in range(1, 11):  # up to 10 pages per path
            url = f"{base}{path}" + (f"&page={pg}" if pg > 1 else "")
            session.headers.update(random_headers())
            try:
                r = session.get(url, timeout=20)
                soup = BeautifulSoup(r.text, "html.parser")

                # Wide selector net — SAYouth layout varies
                cards = soup.select(
                    ".job-card, .opportunity-card, article, .listing, "
                    "[class*='job'], [class*='opportunity'], .card, li.result"
                )
                new_on_page = 0
                for card in cards:
                    title_el = card.select_one("h2, h3, h4, .title, [class*='title'], a")
                    company_el = card.select_one(".company, .employer, .organisation, [class*='company']")
                    location_el = card.select_one(".location, .area, [class*='location'], [class*='province']")
                    link_el = card.select_one("a[href]")

                    title = _clean(title_el.get_text()) if title_el else ""
                    if not title or len(title) < 4:
                        continue
                    key = title.lower()[:60]
                    if key in seen:
                        continue
                    seen.add(key)

                    company = _clean(company_el.get_text()) if company_el else "SA Youth"
                    location = _clean(location_el.get_text()) if location_el else "South Africa"
                    href = link_el["href"] if link_el else ""
                    job_url = href if href.startswith("http") else urljoin(base, href)
                    raw_text = card.get_text(separator=" ", strip=True)

                    salary = _extract_salary(raw_text)
                    closing_date = _extract_closing(raw_text)

                    jobs.append(job_record({
                        "title": title,
                        "company": company,
                        "location": location,
                        "salary": salary,
                        "closing_date": closing_date,
                        "apply_email": _find_email(raw_text),
                        "phone": _find_phone(raw_text),
                        "job_type": _detect_job_type(title, raw_text),
                        "docs_required": _extract_docs(raw_text),
                        "url": job_url,
                        "platform": "sayouth",
                        "description": raw_text[:1500],
                        "raw_text": raw_text[:2000],
                    }))
                    new_on_page += 1

                print(f"[SAYouth] {path} page {pg}: {new_on_page} new jobs (total: {len(jobs)})")
                if new_on_page == 0:
                    break  # no new listings on this page, stop paginating

                time.sleep(random.uniform(0.8, 2.0))

            except Exception as e:
                print(f"[SAYouth] Error {path} page {pg}: {e}")
                break

        if len(jobs) >= limit:
            break

    print(f"[SAYouth] Returning {min(len(jobs), limit)} jobs")
    return jobs[:limit]


# ─── ESSA ─────────────────────────────────────────────────────────────────────

def scrape_essa(keywords=None, limit=200):
    """
    Scrape ESSA (Employment Services SA) — paginate up to 10 pages.
    """
    base = "https://essa.labour.gov.za"
    jobs = []
    seen = set()

    search_paths = []
    if keywords:
        search_paths.append(f"/home/search?query={keywords.replace(' ', '+')}")
    search_paths.append("/home/opportunities")
    search_paths.append("/home/opportunities?type=internship")
    search_paths.append("/home/opportunities?type=learnership")

    session = requests.Session()

    for path in search_paths:
        for pg in range(1, 11):
            url = f"{base}{path}" + (f"&page={pg}" if pg > 1 else "")
            session.headers.update(random_headers())
            try:
                r = session.get(url, timeout=20)
                soup = BeautifulSoup(r.text, "html.parser")

                cards = soup.select(
                    ".job, .vacancy, article, .listing, [class*='job'], "
                    "tr, li.result, [class*='vacancy'], [class*='opportunity']"
                )
                new_on_page = 0
                for card in cards:
                    title_el = card.select_one("h2, h3, h4, .title, [class*='title'], a")
                    company_el = card.select_one(".company, .employer, .department, [class*='company']")
                    location_el = card.select_one(".location, .province, [class*='location']")
                    link_el = card.select_one("a[href]")

                    title = _clean(title_el.get_text()) if title_el else ""
                    if not title or len(title) < 4:
                        continue
                    key = title.lower()[:60]
                    if key in seen:
                        continue
                    seen.add(key)

                    company = _clean(company_el.get_text()) if company_el else "Department of Labour"
                    location = _clean(location_el.get_text()) if location_el else "South Africa"
                    href = link_el["href"] if link_el else ""
                    job_url = href if href.startswith("http") else urljoin(base, href)
                    raw_text = card.get_text(separator=" ", strip=True)

                    salary = _extract_salary(raw_text)
                    closing_date = _extract_closing(raw_text)

                    jobs.append(job_record({
                        "title": title,
                        "company": company,
                        "location": location,
                        "salary": salary,
                        "closing_date": closing_date,
                        "apply_email": _find_email(raw_text),
                        "phone": _find_phone(raw_text),
                        "job_type": _detect_job_type(title, raw_text),
                        "docs_required": _extract_docs(raw_text),
                        "url": job_url,
                        "platform": "essa",
                        "description": raw_text[:1500],
                        "raw_text": raw_text[:2000],
                    }))
                    new_on_page += 1

                print(f"[ESSA] {path} page {pg}: {new_on_page} new jobs (total: {len(jobs)})")
                if new_on_page == 0:
                    break

                time.sleep(random.uniform(0.8, 2.0))

            except Exception as e:
                print(f"[ESSA] Error {path} page {pg}: {e}")
                break

        if len(jobs) >= limit:
            break

    print(f"[ESSA] Returning {min(len(jobs), limit)} jobs")
    return jobs[:limit]


# ─── Gov.za ───────────────────────────────────────────────────────────────────

_GOVZA_ENTRY_POINTS = [
    "https://www.gov.za/about-government/government-jobs",
    "https://www.gov.za/jobs",
    "https://www.gov.za/services/find-job",
]


def _scrape_govza_detail(url):
    """Follow a gov.za job link and extract richer data."""
    try:
        r = requests.get(url, headers=random_headers(), timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        raw_text = soup.get_text(separator="\n", strip=True)

        title_el = soup.select_one("h1, h2.page-title, .field-title")
        title = _clean(title_el.get_text()) if title_el else ""
        if not title:
            return None

        salary = _extract_salary(raw_text)
        closing_date = _extract_closing(raw_text)
        location_m = re.search(r'(?:Location|Province|Centre)[:\s]+([^\n]{3,60})', raw_text, re.I)
        location = _clean(location_m.group(1)) if location_m else "South Africa"

        dept_m = re.search(r'(?:Department|Employer|Organisation)[:\s]+([^\n]{3,80})', raw_text, re.I)
        company = _clean(dept_m.group(1)) if dept_m else "South African Government"

        how_to_apply_m = re.search(r'(?:How to Apply|Applications?)[:\s]+([^\n]{10,300})', raw_text, re.I)
        how_to_apply = _clean(how_to_apply_m.group(1)) if how_to_apply_m else ""

        return job_record({
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "closing_date": closing_date,
            "apply_email": _find_email(raw_text),
            "phone": _find_phone(raw_text),
            "job_type": _detect_job_type(title, raw_text),
            "docs_required": _extract_docs(raw_text),
            "how_to_apply": how_to_apply,
            "url": url,
            "platform": "govza",
            "description": raw_text[:2000],
            "raw_text": raw_text[:3000],
        })
    except Exception as e:
        print(f"[GovZA] Detail scrape error {url}: {e}")
        return None


def scrape_govza(keywords=None, limit=200):
    """
    Scrape gov.za job listings — follows detail links for full data.
    Tries multiple entry points and up to 10 pages each.
    """
    jobs = []
    seen = set()
    detail_urls = []

    session = requests.Session()

    for entry in _GOVZA_ENTRY_POINTS:
        for pg in range(1, 6):  # 5 pages per entry point
            url = entry + (f"?page={pg - 1}" if pg > 1 else "")  # Drupal uses 0-indexed pages
            session.headers.update(random_headers())
            try:
                r = session.get(url, timeout=20)
                soup = BeautifulSoup(r.text, "html.parser")

                # Harvest all internal links that look like job listings
                for item in soup.select("li, article, .field-item, .views-row, tr"):
                    raw_text = item.get_text(separator=" ", strip=True)
                    if len(raw_text) < 10:
                        continue
                    link_el = item.select_one("a[href]")
                    if not link_el:
                        continue
                    title = _clean(link_el.get_text())
                    if not title or len(title) < 5:
                        continue
                    href = link_el["href"]
                    job_url = href if href.startswith("http") else urljoin("https://www.gov.za", href)

                    # Quick card-level extraction (no detail fetch yet)
                    key = title.lower()[:60]
                    if key in seen:
                        continue
                    seen.add(key)

                    salary = _extract_salary(raw_text)
                    closing_date = _extract_closing(raw_text)

                    # If enough data on the card, record directly
                    if salary or closing_date or _find_email(raw_text):
                        jobs.append(job_record({
                            "title": title,
                            "company": "South African Government",
                            "location": "South Africa",
                            "salary": salary,
                            "closing_date": closing_date,
                            "apply_email": _find_email(raw_text),
                            "phone": _find_phone(raw_text),
                            "job_type": _detect_job_type(title, raw_text),
                            "docs_required": _extract_docs(raw_text),
                            "url": job_url,
                            "platform": "govza",
                            "description": raw_text[:1500],
                            "raw_text": raw_text[:2000],
                        }))
                    else:
                        # Queue for detail scrape
                        detail_urls.append((title, job_url))

                print(f"[GovZA] {entry} page {pg}: {len(seen)} total seen so far")
                time.sleep(random.uniform(1.0, 2.5))

            except Exception as e:
                print(f"[GovZA] Error {entry} page {pg}: {e}")
                break

        if len(jobs) + len(detail_urls) >= limit:
            break

    # Fetch details for queued URLs
    from .async_http import parallel_fetch
    if detail_urls:
        remaining = limit - len(jobs)
        batch = [u for _, u in detail_urls[:remaining]]
        print(f"[GovZA] Fetching {len(batch)} detail pages...")
        detail_jobs = parallel_fetch(batch, _scrape_govza_detail, max_workers=10)
        for j in detail_jobs:
            if j and j.get('title'):
                jobs.append(j)

    # Deduplicate by title
    seen_final, out = set(), []
    for j in jobs:
        key = j['title'].lower()[:60]
        if key not in seen_final:
            seen_final.add(key)
            out.append(j)

    print(f"[GovZA] Returning {min(len(out), limit)} jobs")
    return out[:limit]
