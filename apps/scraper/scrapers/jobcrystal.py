import requests
from bs4 import BeautifulSoup
from utils.scraper_utils import random_headers, polite_delay, page_delay, job_record, extract_email_priority, extract_closing_date

BASE = "https://www.jobcrystal.co.za"


def scrape_jobcrystal(keywords: str = None, limit: int = 200) -> list:
    jobs = []
    page = 1

    while len(jobs) < limit:
        params = {"q": keywords or "", "page": page}
        try:
            r = requests.get(f"{BASE}/jobs", params=params, headers=random_headers(), timeout=15)
            if r.status_code != 200:
                break
        except Exception as e:
            print(f"[JobCrystal] Request error p{page}: {e}")
            break

        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("div.job-card, article.job, li.job-item, div[class*='vacancy']")

        if not cards:
            break

        for card in cards:
            title_el = card.select_one("h2, h3, .job-title, a.title")
            company_el = card.select_one(".company, .employer")
            loc_el = card.select_one(".location, .city")
            salary_el = card.select_one(".salary, span[class*='salary'], .pay")
            type_el = card.select_one(".job-type, .type")
            link_el = card.select_one("a[href]")

            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            url = ""
            if link_el:
                href = link_el["href"]
                url = href if href.startswith("http") else BASE + href

            salary = salary_el.get_text(strip=True) if salary_el else ""
            job_type = type_el.get_text(strip=True) if type_el else ""

            desc = ""
            closing = ""
            email = ""

            if url:
                polite_delay()
                try:
                    dr = requests.get(url, headers=random_headers(), timeout=15)
                    if dr.status_code == 200:
                        ds = BeautifulSoup(dr.text, "html.parser")
                        body = ds.select_one("div.job-description, .description, main, article")
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
                "job_type":     job_type,
                "closing_date": closing,
                "platform":     "jobcrystal",
            }))

            if len(jobs) >= limit:
                break

        next_btn = soup.select_one("a[rel='next'], a.next, .pagination .next")
        if not next_btn:
            break

        page += 1
        page_delay()

    print(f"[JobCrystal] {len(jobs)} jobs")
    return jobs
