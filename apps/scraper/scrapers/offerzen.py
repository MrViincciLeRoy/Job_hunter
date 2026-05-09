import requests
from bs4 import BeautifulSoup
from utils.scraper_utils import random_headers, polite_delay, page_delay, job_record, extract_email_priority, extract_closing_date

BASE = "https://www.offerzen.com"


def scrape_offerzen(keywords: str = None, limit: int = 200) -> list:
    jobs = []
    page = 1

    while len(jobs) < limit:
        params = {"q": keywords or "developer", "page": page}
        try:
            r = requests.get(f"{BASE}/jobs/software-developer/south-africa", params=params, headers=random_headers(), timeout=15)
            if r.status_code != 200:
                break
        except Exception as e:
            print(f"[OfferZen] Request error p{page}: {e}")
            break

        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("li.job-card, div.job-listing, article[class*='job']")

        if not cards:
            break

        for card in cards:
            title_el = card.select_one("h2, h3, .role-title, .job-title, a")
            company_el = card.select_one(".company-name, .company, span[class*='company']")
            loc_el = card.select_one(".location, span[class*='location'], .city")
            salary_el = card.select_one(".salary, span[class*='salary'], .compensation")
            link_el = card.select_one("a[href]")

            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            url = ""
            if link_el:
                href = link_el["href"]
                url = href if href.startswith("http") else BASE + href

            salary = salary_el.get_text(strip=True) if salary_el else ""

            desc = ""
            closing = ""
            email = ""

            if url:
                polite_delay()
                try:
                    dr = requests.get(url, headers=random_headers(), timeout=15)
                    if dr.status_code == 200:
                        ds = BeautifulSoup(dr.text, "html.parser")
                        body = ds.select_one("div.job-description, .role-description, main article, section.description")
                        desc = body.get_text("\n", strip=True)[:3000] if body else ""
                        closing = extract_closing_date(desc)
                        email = extract_email_priority(description=desc)
                except Exception:
                    pass

            jobs.append(job_record({
                "title":        title,
                "company":      company_el.get_text(strip=True) if company_el else "",
                "location":     loc_el.get_text(strip=True) if loc_el else "South Africa",
                "description":  desc,
                "salary":       salary,
                "url":          url,
                "apply_email":  email,
                "job_type":     "permanent",
                "closing_date": closing,
                "platform":     "offerzen",
            }))

            if len(jobs) >= limit:
                break

        next_btn = soup.select_one("a[rel='next'], a.next, .pagination a[aria-label='Next']")
        if not next_btn:
            break

        page += 1
        page_delay()

    print(f"[OfferZen] {len(jobs)} jobs")
    return jobs
