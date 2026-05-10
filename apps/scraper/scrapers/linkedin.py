"""
LinkedIn job scraper — pure requests + BeautifulSoup, no Selenium/Playwright.

Scrapes LinkedIn's public (no-auth) guest job search endpoint.
No env vars or login required.

Usage:
    jobs = scrape_linkedin("python developer south africa", limit=100)
"""

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlencode
from utils.scraper_utils import (
    job_record,
    extract_email_priority,
    extract_closing_date,
    random_headers,
    polite_delay,
)

BASE_SEARCH = "https://www.linkedin.com/jobs/search"
GUEST_API   = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

SESSION = requests.Session()


def _li_headers():
    base = random_headers()
    base.update({
        "Referer":        "https://www.linkedin.com/jobs/search/",
        "Accept":         "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
    })
    return base


def _search_page(keywords: str, start: int = 0, location: str = "South Africa") -> list:
    """
    Fetch one page of job cards from the LinkedIn guest search API.
    Returns list of stubs: title, company, location, url, job_id.
    """
    params = {
        "keywords": keywords,
        "location": location,
        "start":    start,
        "count":    25,
    }

    url = f"{BASE_SEARCH}?{urlencode(params)}" if start == 0 else f"{GUEST_API}?{urlencode(params)}"

    try:
        r = SESSION.get(url, headers=_li_headers(), timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"[LinkedIn] Search page start={start} error: {e}")
        return []

    soup    = BeautifulSoup(r.text, "lxml")
    cards   = soup.select("div.base-card, li.jobs-search-results__list-item, li")
    results = []

    for card in cards:
        title_el   = card.select_one("h3.base-search-card__title, h3, .job-search-card__title")
        company_el = card.select_one("h4.base-search-card__subtitle, h4, .job-search-card__company-name")
        loc_el     = card.select_one(".job-search-card__location, .base-search-card__metadata span")
        link_el    = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")

        title   = title_el.get_text(strip=True)  if title_el   else ""
        company = company_el.get_text(strip=True) if company_el else ""
        loc     = loc_el.get_text(strip=True)     if loc_el     else "South Africa"
        href    = link_el["href"].split("?")[0]   if link_el    else ""

        if not title or not href:
            continue

        job_id_m = re.search(r"/jobs/view/(\d+)", href)
        results.append({
            "title":    title,
            "company":  company,
            "location": loc,
            "url":      href,
            "job_id":   job_id_m.group(1) if job_id_m else "",
        })

    print(f"[LinkedIn] start={start} → {len(results)} cards")
    return results


def _scrape_detail(stub: dict) -> dict | None:
    """
    Fetch the LinkedIn job detail page and extract full fields.
    Falls back to stub data if the detail page fails.
    """
    url = stub["url"]
    if not url:
        return None

    try:
        r = SESSION.get(url, headers=_li_headers(), timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"[LinkedIn] Detail error {url}: {e}")
        return job_record({
            "title":    stub["title"],
            "company":  stub["company"],
            "location": stub["location"],
            "url":      url,
            "platform": "linkedin",
        })

    soup     = BeautifulSoup(r.text, "lxml")
    raw_text = soup.get_text(separator="\n", strip=True)

    def _text(selector, default=""):
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else default

    title   = _text("h1.top-card-layout__title, h1") or stub["title"]
    company = _text(".topcard__org-name-link, .top-card-layout__card a") or stub["company"]
    loc     = _text(".topcard__flavor--bullet, .top-card-layout__second-subline span") or stub["location"]

    desc_el = soup.select_one(
        ".show-more-less-html__markup, "
        ".description__text, "
        "section.description div"
    )
    description = desc_el.get_text(separator="\n", strip=True) if desc_el else ""

    job_type = ""
    salary   = ""
    for item in soup.select("li.description__job-criteria-item"):
        header = item.select_one("h3")
        value  = item.select_one("span")
        if not header or not value:
            continue
        h = header.get_text(strip=True).lower()
        v = value.get_text(strip=True)
        if "employment type" in h:
            job_type = v
        elif "salary" in h or "compensation" in h:
            salary = v

    if not salary:
        m = re.search(r'(?:salary|compensation|package)[:\s]+([^\n]{5,60})', raw_text, re.I)
        if m:
            salary = m.group(1).strip()

    return job_record({
        "title":        title,
        "company":      company,
        "location":     loc,
        "salary":       salary,
        "job_type":     job_type,
        "closing_date": extract_closing_date(raw_text),
        "apply_email":  extract_email_priority(description=description, raw_text=raw_text),
        "url":          url,
        "platform":     "linkedin",
        "description":  description[:2000],
        "raw_text":     raw_text[:3000],
    })


def scrape_linkedin(keywords: str = None, limit: int = 200) -> list:
    """
    Scrape LinkedIn public job listings — no login required.

    Args:
        keywords: search string, e.g. "python developer south africa"
        limit:    max jobs to return

    Returns:
        list of job_record dicts
    """
    query    = keywords or "developer south africa"
    stubs    = []
    start    = 0
    per_page = 25

    print(f"[LinkedIn] Collecting listings for '{query}'...")

    while len(stubs) < limit:
        page = _search_page(query, start=start)
        if not page:
            break
        stubs.extend(page)
        if len(page) < per_page:
            break
        start += per_page
        polite_delay(1.5, 3.0)

    stubs = stubs[:limit]
    print(f"[LinkedIn] {len(stubs)} stubs — fetching details...")

    jobs = []
    for i, stub in enumerate(stubs):
        rec = _scrape_detail(stub)
        if rec and rec.get("title"):
            jobs.append(rec)
            print(f"  [{i+1}/{len(stubs)}] {rec['title']} @ {rec['company']}")
        polite_delay(0.8, 2.0)

    print(f"[LinkedIn] Done — {len(jobs)} jobs")
    return jobs