import requests
from bs4 import BeautifulSoup
import re
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-ZA,en;q=0.9",
}
BASE = "https://www.careerjunction.co.za"
IT_URL = "https://www.careerjunction.co.za/jobs/results?Location=1&SortBy=Relevance&rbcat=16&lr=0"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
SKIP = {"noreply", "no-reply", "donotreply", "info@careerjunction", "support@careerjunction", "privacy", "legal"}


def _find_email(text: str) -> str:
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP):
            return m.group(0)
    return ""


def _parse_job_cards(soup, base_url=BASE) -> list:
    jobs = []

    # Try JSON-LD first
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") in ("JobPosting", "jobPosting"):
                    title = item.get("title", "")
                    org = item.get("hiringOrganization", {})
                    company = org.get("name", "") if isinstance(org, dict) else ""
                    loc = item.get("jobLocation", {})
                    location = "South Africa"
                    if isinstance(loc, dict):
                        addr = loc.get("address", {})
                        location = addr.get("addressLocality", "") or addr.get("addressRegion", "South Africa")
                    desc = item.get("description", "")
                    url = item.get("url", "")
                    email = _find_email(desc)
                    if title:
                        jobs.append({
                            "title": title, "company": company, "location": location,
                            "description": desc[:800], "url": url,
                            "apply_email": email, "platform": "careerjunction_it",
                        })
        except Exception:
            pass

    if jobs:
        return jobs

    # Fallback: HTML selectors — CJ uses various class patterns
    selector_attempts = [
        (".job-result-item", "h2,h3,.job-title,.position-title", ".company-name,.employer,.company"),
        (".listing-item", "h2,h3,.title", ".company,.employer"),
        ("article.job", "h2,h3", ".company"),
        (".job-card", "h2,h3,[class*='title']", "[class*='company'],[class*='employer']"),
        ("[class*='job-result']", "h2,h3,a", ".company,.employer"),
        ("li[class*='job']", "h2,h3,a", ".company,.employer"),
        ("[class*='JobCard']", "[class*='title']", "[class*='company']"),
        ("[class*='resultItem']", "h2,h3,a", "[class*='company']"),
    ]

    for card_sel, title_sel, company_sel in selector_attempts:
        cards = soup.select(card_sel)
        if not cards:
            continue
        for card in cards:
            title_el = card.select_one(title_sel)
            company_el = card.select_one(company_sel)
            link_el = card.select_one("a[href]")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title or len(title) < 3:
                continue
            company = company_el.get_text(strip=True) if company_el else ""
            href = link_el["href"] if link_el else ""
            job_url = base_url + href if href.startswith("/") else href
            text = card.get_text(separator=" ", strip=True)
            email = _find_email(text)
            jobs.append({
                "title": title, "company": company, "location": "South Africa",
                "description": text[:600], "url": job_url,
                "apply_email": email, "platform": "careerjunction_it",
            })
        if jobs:
            return jobs

    return jobs


def scrape_careerjunction_it(keywords: str = None, limit: int = 30) -> list:
    """Scrape CJ IT category. keywords is used to filter results if provided."""
    all_jobs = []

    # Always hit the IT category URL first
    urls = [IT_URL]

    # Also add keyword search within IT category if keywords provided
    if keywords:
        q = keywords.strip().replace(" ", "+")
        urls.append(f"{BASE}/jobs/results?Keywords={q}&Location=1&SortBy=Relevance&rbcat=16&lr=0")

    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            jobs = _parse_job_cards(soup)
            all_jobs.extend(jobs)

            # Follow pagination up to 3 pages
            for page in range(2, 4):
                next_url = url + f"&pg={page}" if "?" in url else url + f"?pg={page}"
                try:
                    rp = requests.get(next_url, headers=HEADERS, timeout=15)
                    sp = BeautifulSoup(rp.text, "html.parser")
                    page_jobs = _parse_job_cards(sp)
                    if not page_jobs:
                        break
                    all_jobs.extend(page_jobs)
                except Exception:
                    break

        except Exception as e:
            print(f"[CJ-IT] Error on {url}: {e}")

    # Deduplicate by title+company
    seen = set()
    unique = []
    for j in all_jobs:
        key = (j["title"].lower(), j.get("company", "").lower())
        if key not in seen:
            seen.add(key)
            unique.append(j)

    return unique[:limit]
