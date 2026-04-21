import requests
from bs4 import BeautifulSoup
import re
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-ZA,en;q=0.9",
}
BASE = "https://www.pnet.co.za"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")

SKIP_EMAILS = {"noreply", "no-reply", "donotreply", "support@pnet", "info@pnet", "privacy", "legal"}


def _find_email(text: str) -> str:
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP_EMAILS):
            return m.group(0)
    return ""


def _try_json_ld(soup) -> list:
    """Extract jobs from JSON-LD structured data — works even when HTML selectors fail."""
    jobs = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") in ("JobPosting", "jobPosting"):
                    title = item.get("title", "")
                    company = ""
                    org = item.get("hiringOrganization", {})
                    if isinstance(org, dict):
                        company = org.get("name", "")
                    location = ""
                    loc = item.get("jobLocation", {})
                    if isinstance(loc, dict):
                        addr = loc.get("address", {})
                        location = addr.get("addressLocality", "") or addr.get("addressRegion", "") or "South Africa"
                    url = item.get("url", "") or item.get("identifier", "")
                    desc = item.get("description", "")
                    email = _find_email(desc)
                    if title:
                        jobs.append({"title": title, "company": company, "location": location or "South Africa", "description": desc[:600], "url": url, "apply_email": email, "platform": "pnet"})
        except Exception:
            pass
    return jobs


def scrape_pnet(keywords: str, limit: int = 20) -> list:
    query = keywords.strip().replace(" ", "-").lower()
    urls_to_try = [
        f"{BASE}/jobs/{query}/",
        f"{BASE}/jobs/{query.replace('-', '%20')}/",
        f"{BASE}/jobs/?keywords={keywords.replace(' ', '+')}",
    ]

    for url in urls_to_try:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")

            # Try JSON-LD first
            jobs = _try_json_ld(soup)
            if jobs:
                return jobs[:limit]

            # Try many selector patterns (PNet changes their markup frequently)
            selector_sets = [
                ("article.job-card", "h2,h3,.job-title,[data-testid='job-title']", ".company,[data-testid='company-name'],.employer"),
                ("[data-job-id]", "h2,h3,.title", ".company,.employer"),
                (".job-item", "h2,h3,a", ".company,.employer"),
                (".search-result", "h2,h3,a.job-title", ".company"),
                ("li[class*='job']", "h2,h3", ".company"),
                (".listing", "h2,h3,a", ".company,.employer"),
                ("article", "h2,h3", ".company,.employer"),
                ("[class*='JobCard']", "[class*='title']", "[class*='company'],[class*='employer']"),
            ]

            for card_sel, title_sel, company_sel in selector_sets:
                cards = soup.select(card_sel)[:limit]
                if not cards:
                    continue
                jobs = []
                for card in cards:
                    title_el = card.select_one(title_sel)
                    company_el = card.select_one(company_sel)
                    link_el = card.select_one("a[href]")
                    title = title_el.get_text(strip=True) if title_el else ""
                    if not title or len(title) < 3:
                        continue
                    company = company_el.get_text(strip=True) if company_el else ""
                    href = link_el["href"] if link_el else ""
                    job_url = BASE + href if href.startswith("/") else href
                    text = card.get_text(separator=" ", strip=True)
                    email = _find_email(text)
                    jobs.append({"title": title, "company": company, "location": "South Africa", "description": text[:500], "url": job_url, "apply_email": email, "platform": "pnet"})
                if jobs:
                    return jobs

        except Exception as e:
            print(f"[PNet] Error on {url}: {e}")
            continue

    print("[PNet] All URL attempts failed or returned 0 jobs")
    return []
