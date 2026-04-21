import requests
from bs4 import BeautifulSoup
import re

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
BASE = "https://www.pnet.co.za"


def _find_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", text)
    return match.group(0) if match else ""


def scrape_pnet(keywords: str, limit: int = 20) -> list:
    query = keywords.strip().replace(" ", "-").lower()
    url = f"{BASE}/en/find-jobs/{query}/"
    jobs = []

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        cards = soup.select("article.job-card, [data-job-id], .job-item")[:limit]

        for card in cards:
            title_el = card.select_one("h2, h3, .job-title, [data-testid='job-title']")
            company_el = card.select_one(".company, [data-testid='company-name'], .employer")
            link_el = card.select_one("a[href]")

            title = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            href = link_el["href"] if link_el else ""
            job_url = BASE + href if href.startswith("/") else href

            email = _find_email(card.get_text())

            if title:
                jobs.append({
                    "title": title,
                    "company": company,
                    "location": "South Africa",
                    "description": card.get_text(separator=" ", strip=True)[:500],
                    "url": job_url,
                    "apply_email": email,
                    "platform": "pnet",
                })
    except Exception as e:
        print(f"[PNet] Error: {e}")

    return jobs
