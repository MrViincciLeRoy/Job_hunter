import re
import time
import requests
from bs4 import BeautifulSoup
from utils.scraper_utils import random_headers, polite_delay, page_delay, job_record
from apps.scraper.scrapers.async_http import parallel_fetch

BASE_URL = "https://www.careers24.com"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")
SKIP_DOMAINS = {
    "careers24.com", "pnet.co.za", "careerjunction.co.za", "jobmail.co.za",
    "gumtree.co.za", "linkedin.com", "indeed.com", "glassdoor.com",
}
SKIP_PREFIXES = {"noreply", "no-reply", "donotreply", "privacy", "legal", "support", "info", "admin", "webmaster"}


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        local, domain = e.split("@", 1)
        if domain in SKIP_DOMAINS or local in SKIP_PREFIXES:
            continue
        return m.group(0)
    return ""


def _clean(t):
    return re.sub(r"\s+", " ", t or "").strip()


def _collect_links(keywords, max_pages=60):
    session = requests.Session()
    seen = set()
    all_links = []

    start_urls = []
    if keywords:
        q = keywords.strip().replace(" ", "+")
        start_urls.append(f"{BASE_URL}/jobs/?k={q}&l=south+africa&sort=dateposted")
    start_urls.append(f"{BASE_URL}/jobs/se-it/rmt-incl/?sort=dateposted&ref=sbj")
    start_urls.append(f"{BASE_URL}/jobs/?sort=dateposted")

    for start_url in start_urls:
        session.headers.update(random_headers())
        for pg in range(1, max_pages + 1):
            if pg == 1:
                url = start_url
            elif "?" in start_url:
                url = f"{start_url}&startIndex={(pg - 1) * 20}"
            else:
                url = f"{start_url.rstrip('/')}/pg{pg}/"
            try:
                r = session.get(url, timeout=25)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                found = []
                for a in soup.find_all("a", href=re.compile(r"/jobs/adverts/\d+")):
                    href = a["href"]
                    full = href if href.startswith("http") else BASE_URL + href
                    key = full.split("?")[0]
                    m = re.search(r"/adverts/(\d+)-", key)
                    if m and key not in seen:
                        seen.add(key)
                        found.append(key)
                if not found:
                    print(f"[Careers24] No more results at page {pg}")
                    break
                all_links.extend(found)
                print(f"[Careers24] Page {pg}: {len(found)} links (total: {len(all_links)})")
                page_delay()
            except Exception as e:
                print(f"[Careers24] Page {pg} error: {e}")
                break
        if all_links:
            break

    return all_links


def _scrape_detail(url):
    try:
        r = requests.get(url, headers=random_headers(), timeout=20)
        r.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(separator="\n")

    title_el = soup.select_one("h1")
    title = _clean(title_el.get_text()) if title_el else ""
    if not title:
        return None

    emp_m = re.search(r"Employer[:\s]+(.+?)(?:\n|$)", text, re.I)
    company = _clean(emp_m.group(1)) if emp_m else ""

    loc_el = soup.select_one('a[href*="/jobs/lc-"]')
    location = _clean(loc_el.get_text()) if loc_el else "South Africa"

    salary_m = re.search(r"(?:Salary|Remuneration|Package)[:\s]*([^\n]{3,80})", text, re.I)
    salary = _clean(salary_m.group(1)) if salary_m else ""

    job_type_m = re.search(r"(?:Job Type|Contract Type|Employment Type)[:\s]*([^\n]{3,50})", text, re.I)
    job_type = _clean(job_type_m.group(1)) if job_type_m else ""

    closing_m = re.search(r"(?:Closing Date|Deadline)[:\s]*([^\n]{3,50})", text, re.I)
    closing_date = _clean(closing_m.group(1)) if closing_m else ""

    duties_m = re.search(
        r"(?:Duties\s+and\s+Responsibilities|Duties|Responsibilities)[:\s]*\n+(.+?)(?:\n{2,}|Minimum\s+Requirements|Requirements|Skills|Salary|$)",
        text, re.DOTALL | re.I
    )
    req_m = re.search(
        r"(?:Minimum\s+Requirements|Requirements|Qualifications)[:\s]*\n+(.+?)(?:\n{2,}|Knowledge|Skills|Salary|$)",
        text, re.DOTALL | re.I
    )
    description = " ".join(filter(None, [
        _clean(duties_m.group(1)) if duties_m else "",
        _clean(req_m.group(1)) if req_m else "",
    ]))
    if not description:
        desc_el = soup.select_one("[class*='description'], article, main")
        description = _clean(desc_el.get_text("\n")) if desc_el else ""

    apply_m = re.search(r"(?:How to Apply|To Apply|Application Process|Send.*?CV|Apply.*?via)[:\s]*([^\n]{10,200})", text, re.I)
    how_to_apply = _clean(apply_m.group(1)) if apply_m else ""

    return job_record({
        "title": title,
        "company": company,
        "location": location,
        "description": description[:2000],
        "url": url,
        "apply_email": _find_email(text),
        "platform": "careers24",
        "salary": salary,
        "job_type": job_type,
        "closing_date": closing_date,
        "how_to_apply": how_to_apply,
        "raw_text": text[:3000],
    })


def scrape_careers24(keywords=None, limit=500):
    links = _collect_links(keywords, max_pages=60)
    if not links:
        print("[Careers24] No links found")
        return []

    urls = links[:limit]
    print(f"[Careers24] Fetching {len(urls)} detail pages in parallel...")
    jobs = parallel_fetch(urls, _scrape_detail, max_workers=16)
    jobs = [j for j in jobs if j and j.get("title")]
    print(f"[Careers24] {len(jobs)} jobs scraped")
    return jobs
