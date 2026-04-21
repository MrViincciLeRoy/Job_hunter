import requests
from bs4 import BeautifulSoup
import re

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
BASE = "https://www.jobmail.co.za"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")


def _find_email(text):
    m = EMAIL_RE.search(text)
    return m.group(0) if m else ""


def scrape_jobmail(keywords: str, limit: int = 20) -> list:
    query = keywords.strip().replace(" ", "+")
    url = f"{BASE}/jobs/{query.replace('+', '-').lower()}"
    jobs = []

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        cards = soup.select(".job-listing, .listing-item, article, [class*='job-result']")[:limit]

        for card in cards:
            title_el = card.select_one("h2, h3, h4, .job-title, a[href*='job']")
            company_el = card.select_one(".company, .employer, [class*='company']")
            link_el = card.select_one("a[href]")

            title = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            href = link_el["href"] if link_el else ""
            job_url = BASE + href if href.startswith("/") else href

            text = card.get_text()
            email = _find_email(text)

            if title and len(title) > 3:
                jobs.append({
                    "title": title,
                    "company": company,
                    "location": "South Africa",
                    "description": text[:600],
                    "url": job_url,
                    "apply_email": email,
                    "platform": "jobmail",
                })
    except Exception as e:
        print(f"[JobMail] Error: {e}")

    return jobs
