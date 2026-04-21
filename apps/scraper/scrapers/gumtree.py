import requests
from bs4 import BeautifulSoup
import re

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
BASE = "https://www.gumtree.co.za"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
SKIP = {"noreply", "no-reply", "donotreply", "support@gumtree", "info@gumtree"}


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP):
            return e
    return ""


def scrape_gumtree(keywords: str, limit: int = 20) -> list:
    query = keywords.strip().replace(" ", "+")
    url = f"{BASE}/results/q-{query.replace('+', '-')}/cat-Jobs"
    jobs = []

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        cards = soup.select("article.listing-result, .search-results article, li.ad-listing")[:limit]

        for card in cards:
            title_el = card.select_one("h2, h3, .listing-title, [class*='title']")
            link_el = card.select_one("a[href*='/a-']")
            location_el = card.select_one(".ad-location, [class*='location']")

            title = title_el.get_text(strip=True) if title_el else ""
            href = link_el["href"] if link_el else ""
            job_url = BASE + href if href.startswith("/") else href
            location = location_el.get_text(strip=True) if location_el else "South Africa"

            text = card.get_text()
            email = _find_email(text)

            if title and len(title) > 3:
                jobs.append({
                    "title": title,
                    "company": "Via Gumtree",
                    "location": location,
                    "description": text[:600],
                    "url": job_url,
                    "apply_email": email,
                    "platform": "gumtree",
                })
    except Exception as e:
        print(f"[Gumtree] Error: {e}")

    return jobs
