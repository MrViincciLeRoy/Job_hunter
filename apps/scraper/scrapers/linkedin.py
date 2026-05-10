"""
LinkedIn job scraper using joeyism/linkedin_scraper.

Requirements:
    pip install linkedin-scraper selenium
    Chrome + chromedriver installed and on PATH

Env vars needed:
    LINKEDIN_EMAIL    — your LinkedIn login email
    LINKEDIN_PASSWORD — your LinkedIn password

Usage:
    jobs = scrape_linkedin("python developer", limit=100)
"""

import os
import time
import random
from utils.scraper_utils import job_record, extract_email_priority, extract_closing_date

try:
    from linkedin_scraper import JobSearch, actions
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    _LINKEDIN_AVAILABLE = True
except ImportError:
    _LINKEDIN_AVAILABLE = False


def _make_driver(headless: bool = True):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=opts)


def _job_to_record(lj) -> dict:
    """
    Convert a linkedin_scraper Job/JobListing object to our standard job_record dict.
    Attribute names vary slightly between versions — we check defensively.
    """
    def _attr(*names, default=""):
        for n in names:
            v = getattr(lj, n, None)
            if v:
                return str(v).strip()
        return default

    title        = _attr("job_title", "title", "name")
    company      = _attr("company", "company_name", "employer")
    location     = _attr("location", "job_location")
    description  = _attr("job_description", "description", "summary")
    url          = _attr("linkedin_url", "url", "job_url")
    salary       = _attr("salary", "compensation")
    job_type     = _attr("employment_type", "job_type", "work_type")
    closing_date = extract_closing_date(description)
    apply_email  = extract_email_priority(description=description, raw_text=description)

    return job_record({
        "title":       title,
        "company":     company,
        "location":    location or "South Africa",
        "salary":      salary,
        "job_type":    job_type,
        "closing_date": closing_date,
        "apply_email": apply_email,
        "url":         url,
        "platform":    "linkedin",
        "description": description[:2000],
        "raw_text":    description[:3000],
    })


def scrape_linkedin(keywords: str = None, limit: int = 200) -> list:
    """
    Scrape LinkedIn job listings.

    Args:
        keywords: search string, e.g. "python developer south africa"
        limit:    max jobs to return

    Returns:
        list of job_record dicts
    """
    if not _LINKEDIN_AVAILABLE:
        print("[LinkedIn] linkedin-scraper or selenium not installed. "
              "Run: pip install linkedin-scraper selenium")
        return []

    email    = os.getenv("LINKEDIN_EMAIL", "")
    password = os.getenv("LINKEDIN_PASSWORD", "")

    if not email or not password:
        print("[LinkedIn] LINKEDIN_EMAIL / LINKEDIN_PASSWORD env vars not set.")
        return []

    driver = None
    try:
        print("[LinkedIn] Launching Chrome driver...")
        driver = _make_driver(headless=True)

        print("[LinkedIn] Logging in...")
        actions.login(driver, email, password)
        time.sleep(random.uniform(2.0, 4.0))

        search_query = keywords or "developer south africa"
        print(f"[LinkedIn] Searching: '{search_query}'")

        job_search = JobSearch(driver=driver, close_on_complete=False, scrape=False)
        job_search.search(search_query)
        time.sleep(random.uniform(2.0, 3.5))

        # Scrape up to `limit` listings
        raw_jobs = job_search.jobs[:limit] if hasattr(job_search, "jobs") else []

        print(f"[LinkedIn] Found {len(raw_jobs)} raw listings — scraping details...")

        results = []
        for i, lj in enumerate(raw_jobs):
            try:
                # Trigger detail scrape if the object supports it
                if hasattr(lj, "scrape"):
                    lj.scrape(close_on_complete=False)
                    time.sleep(random.uniform(0.8, 1.8))

                rec = _job_to_record(lj)
                if rec.get("title"):
                    results.append(rec)
                    print(f"  [{i+1}/{len(raw_jobs)}] {rec['title']} @ {rec['company']}")
            except Exception as e:
                print(f"  [LinkedIn] Detail error job {i+1}: {e}")
                continue

        print(f"[LinkedIn] Returning {len(results)} jobs")
        return results

    except Exception as e:
        print(f"[LinkedIn] Scrape failed: {e}")
        import traceback
        traceback.print_exc()
        return []

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
