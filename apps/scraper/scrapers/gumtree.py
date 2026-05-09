import requests
from bs4 import BeautifulSoup
from utils.scraper_utils import random_headers, polite_delay, page_delay, job_record, extract_email_priority, extract_closing_date, is_hire_me_post

BASE = "https://www.gumtree.co.za"


def scrape_gumtree(keywords: str = None, limit: int = 200) -> list:
    jobs = []
    page = 1

    while len(jobs) < limit:
        q = keywords or "job vacancy"
        url = f"{BASE}/jobs?q={q}&page={page}"
        try:
            r = requests.get(url, headers=random_headers(), timeout=15)
            if r.status_code != 200:
                break
        except Exception as e:
            print(f"[Gumtree] Request error p{page}: {e}")
            break

        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("li.listing-result, article.listing, div.listing-card, div[class*='result']")

        if not cards:
            break

        for card in cards:
            title_el = card.select_one("h2, h3, .listing-title, a.title")
            loc_el = card.select_one(".location, span[class*='location'], .suburb")
            link_el = card.select_one("a[href]")

            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            href = link_el["href"] if link_el else ""
            detail_url = href if href.startswith("http") else BASE + href

            desc = ""
            company = ""
            closing = ""
            email = ""

            if detail_url:
                polite_delay()
                try:
                    dr = requests.get(detail_url, headers=random_headers(), timeout=15)
                    if dr.status_code == 200:
                        ds = BeautifulSoup(dr.text, "html.parser")
                        body = ds.select_one("div.description-content, div.view-ad-description, .ad-description, article")
                        desc = body.get_text("\n", strip=True)[:3000] if body else ""
                        company_el = ds.select_one(".seller-name, .advertiser-name, .user-name")
                        company = company_el.get_text(strip=True) if company_el else ""
                        closing = extract_closing_date(desc)
                        email = extract_email_priority(description=desc)
                except Exception:
                    pass

            # Filter out "hire me" posts — common on Gumtree
            if is_hire_me_post(title, desc):
                continue

            jobs.append(job_record({
                "title":        title,
                "company":      company,
                "location":     loc_el.get_text(strip=True) if loc_el else "South Africa",
                "description":  desc,
                "url":          detail_url,
                "apply_email":  email,
                "closing_date": closing,
                "platform":     "gumtree",
            }))

            if len(jobs) >= limit:
                break

        next_btn = soup.select_one("a[rel='next'], a.next-page, li.next a")
        if not next_btn:
            break

        page += 1
        page_delay()

    print(f"[Gumtree] {len(jobs)} jobs")
    return jobs
