import requests
from bs4 import BeautifulSoup
import re

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
BASE = "https://www.careers24.com"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")


def _find_email(text):
    m = EMAIL_RE.search(text)
    return m.group(0) if m else ""


def scrape_careers24(keywords: str, limit: int = 20) -> list:
    query = keywords.strip().replace(" ", "+")
    url = f"{BASE}/jobs/?k={query}&l=south+africa"
    jobs = []

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        cards = soup.select("li.job-item, article.job-card, .search-result-item, [data-job-id]")[:limit]

        if not cards:
            # fallback: try generic article/section tags
            cards = soup.select("article, .listing")[:limit]

        for card in cards:
            title_el = card.select_one("h2, h3, h4, .job-title, [class*='title']")
            company_el = card.select_one(".company, .employer, [class*='company']")
            link_el = card.select_one("a[href*='/jobs/']")

            title = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            href = link_el["href"] if link_el else ""
            job_url = BASE + href if href.startswith("/") else href

            text = card.get_text()
            email = _find_email(text)

            if title:
                jobs.append({
                    "title": title,
                    "company": company,
                    "location": "South Africa",
                    "description": text[:600],
                    "url": job_url,
                    "apply_email": email,
                    "platform": "careers24",
                })
    except Exception as e:
        print(f"[Careers24] Error: {e}")

    return jobs
