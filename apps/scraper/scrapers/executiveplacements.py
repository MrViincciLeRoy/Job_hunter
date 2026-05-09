import requests
from bs4 import BeautifulSoup
from utils.scraper_utils import random_headers, polite_delay, page_delay, job_record, extract_email_priority, extract_closing_date

BASE = "https://www.executiveplacements.com"


def scrape_executiveplacements(keywords: str = None, limit: int = 200) -> list:
    jobs = []
    page = 1

    while len(jobs) < limit:
        params = {"q": keywords or "", "pg": page}
        try:
            r = requests.get(f"{BASE}/Jobs/", params=params, headers=random_headers(), timeout=15)
            if r.status_code != 200:
                break
        except Exception as e:
            print(f"[ExecutivePlacements] Request error p{page}: {e}")
            break

        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("div.job, div.jobItem, li.job-result, div[class*='job-listing']")

        if not cards:
            break

        for card in cards:
            title_el = card.select_one("h2, h3, a.jobtitle, .job-title")
            company_el = card.select_one(".company, .employer, span[class*='company']")
            loc_el = card.select_one(".location, span[class*='location']")
            salary_el = card.select_one(".salary, span[class*='salary']")
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
                        body = ds.select_one("div.job-description, div#jobDescription, div.description, main")
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
                "platform":     "executiveplacements",
            }))

            if len(jobs) >= limit:
                break

        next_btn = soup.select_one("a[rel='next'], a.next, .paging a:last-child")
        if not next_btn:
            break

        page += 1
        page_delay()

    print(f"[ExecutivePlacements] {len(jobs)} jobs")
    return jobs
