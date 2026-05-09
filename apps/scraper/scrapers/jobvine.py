import requests
from bs4 import BeautifulSoup
from utils.scraper_utils import random_headers, polite_delay, page_delay, job_record, extract_email_priority, extract_closing_date

BASE = "https://www.jobvine.co.za"


def scrape_jobvine(keywords: str = None, limit: int = 200) -> list:
    jobs = []
    page = 1

    while len(jobs) < limit:
        params = {"q": keywords or "", "page": page}
        try:
            r = requests.get(f"{BASE}/jobs", params=params, headers=random_headers(), timeout=15)
            if r.status_code != 200:
                break
        except Exception as e:
            print(f"[Jobvine] Request error p{page}: {e}")
            break

        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("div.job-listing, article.job-card, div.jobvine-job")

        if not cards:
            # fallback selector
            cards = soup.select("div[class*='job']")

        if not cards:
            break

        for card in cards:
            title_el = card.select_one("h2, h3, a.job-title, .title")
            company_el = card.select_one(".company, .employer, span[class*='company']")
            loc_el = card.select_one(".location, span[class*='location']")
            link_el = card.select_one("a[href]")

            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            url = ""
            if link_el:
                href = link_el["href"]
                url = href if href.startswith("http") else BASE + href

            desc = ""
            closing = ""
            email = ""

            if url:
                polite_delay()
                try:
                    dr = requests.get(url, headers=random_headers(), timeout=15)
                    if dr.status_code == 200:
                        ds = BeautifulSoup(dr.text, "html.parser")
                        body = ds.select_one("div.job-description, div.description, main, article")
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
                "url":          url,
                "apply_email":  email,
                "closing_date": closing,
                "platform":     "jobvine",
            }))

            if len(jobs) >= limit:
                break

        next_btn = soup.select_one("a[rel='next'], a.next, li.next a")
        if not next_btn:
            break

        page += 1
        page_delay()

    print(f"[Jobvine] {len(jobs)} jobs")
    return jobs
