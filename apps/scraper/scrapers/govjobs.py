from apps.scraper.scrapers.dpsa import scrape_dpsa  # noqa: F401 — re-export for backwards compat

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-ZA,en;q=0.9",
}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
SKIP_EMAILS = {"noreply", "no-reply", "donotreply", "webmaster", "admin", "privacy", "legal", "info@dpsa"}


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP_EMAILS):
            return m.group(0)
    return ""


def scrape_sayouth(keywords=None, limit=30):
    base = "https://sayouth.mobi"
    jobs = []
    urls = [f"{base}/Jobs"]
    if keywords:
        urls.insert(0, f"{base}/Jobs?search={keywords.replace(' ', '+')}")

    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select(".job-card, .opportunity-card, article, .listing, [class*='job'], .card")
            for card in cards[:limit]:
                title_el = card.select_one("h2, h3, h4, .title, [class*='title'], a")
                company_el = card.select_one(".company, .employer, .organisation")
                location_el = card.select_one(".location, .area, [class*='location']")
                link_el = card.select_one("a[href]")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title or len(title) < 4:
                    continue
                company = company_el.get_text(strip=True) if company_el else "SA Youth"
                location = location_el.get_text(strip=True) if location_el else "South Africa"
                href = link_el["href"] if link_el else ""
                job_url = href if href.startswith("http") else urljoin(base, href)
                text = card.get_text(separator=" ", strip=True)
                jobs.append({
                    "title": title, "company": company, "location": location,
                    "description": text[:600], "url": job_url,
                    "apply_email": _find_email(text), "platform": "sayouth",
                })
            if jobs:
                break
        except Exception as e:
            print(f"[SAYouth] Error: {e}")

    if keywords:
        kws = keywords.lower().split()
        jobs = [j for j in jobs if any(kw in j["title"].lower() or kw in j["description"].lower() for kw in kws)]
    return jobs[:limit]


def scrape_essa(keywords=None, limit=30):
    base = "https://essa.labour.gov.za"
    jobs = []
    urls = [f"{base}/home/opportunities"]
    if keywords:
        urls.insert(0, f"{base}/home/search?query={keywords.replace(' ', '+')}")

    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select(".job, .vacancy, article, .listing, [class*='job'], tr, li.result")
            for card in cards[:limit]:
                title_el = card.select_one("h2, h3, h4, .title, a")
                company_el = card.select_one(".company, .employer, .department")
                location_el = card.select_one(".location, .province")
                link_el = card.select_one("a[href]")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title or len(title) < 4:
                    continue
                company = company_el.get_text(strip=True) if company_el else "Department of Labour"
                location = location_el.get_text(strip=True) if location_el else "South Africa"
                href = link_el["href"] if link_el else ""
                job_url = href if href.startswith("http") else urljoin(base, href)
                text = card.get_text(separator=" ", strip=True)
                jobs.append({
                    "title": title, "company": company, "location": location,
                    "description": text[:600], "url": job_url,
                    "apply_email": _find_email(text), "platform": "essa",
                })
            if jobs:
                break
        except Exception as e:
            print(f"[ESSA] Error: {e}")

    return jobs[:limit]


def scrape_govza(keywords=None, limit=30):
    base = "https://www.gov.za"
    jobs = []

    try:
        r = requests.get("https://www.gov.za/about-government/government-jobs", headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select("li, article, .field-item, .views-row"):
            text = item.get_text(separator=" ", strip=True)
            if len(text) < 15:
                continue
            link_el = item.select_one("a[href]")
            if not link_el:
                continue
            title = link_el.get_text(strip=True)
            href = link_el["href"]
            job_url = href if href.startswith("http") else urljoin(base, href)
            if title and len(title) > 5:
                jobs.append({
                    "title": title, "company": "South African Government",
                    "location": "South Africa", "description": text[:600],
                    "url": job_url, "apply_email": _find_email(text), "platform": "govza",
                })
    except Exception as e:
        print(f"[GovZA] Error: {e}")

    if keywords:
        kws = keywords.lower().split()
        jobs = [j for j in jobs if any(kw in j["title"].lower() or kw in j["description"].lower() for kw in kws)]

    seen, out = set(), []
    for j in jobs:
        key = j["title"].lower()[:50]
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out[:limit]
