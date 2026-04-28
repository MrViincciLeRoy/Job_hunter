import requests
from bs4 import BeautifulSoup
import re
import json
import time
import random
from utils.scraper_utils import random_headers, polite_delay, page_delay, job_record

BASE = "https://www.pnet.co.za"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
SKIP_EMAILS = {"noreply", "no-reply", "donotreply", "support@pnet", "info@pnet", "privacy", "legal"}


def _find_email(text):
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP_EMAILS):
            return m.group(0)
    return ""


def _try_json_ld(soup):
    jobs = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") in ("JobPosting", "jobPosting"):
                    title = item.get("title", "")
                    company = ""
                    org = item.get("hiringOrganization", {})
                    if isinstance(org, dict):
                        company = org.get("name", "")
                    location = ""
                    loc = item.get("jobLocation", {})
                    if isinstance(loc, dict):
                        addr = loc.get("address", {})
                        location = addr.get("addressLocality", "") or addr.get("addressRegion", "") or "South Africa"
                    url = item.get("url", "") or item.get("identifier", "")
                    desc = item.get("description", "")
                    salary_raw = ""
                    sal = item.get("baseSalary", {})
                    if isinstance(sal, dict):
                        val = sal.get("value", {})
                        if isinstance(val, dict):
                            mn = val.get("minValue", "")
                            mx = val.get("maxValue", "")
                            salary_raw = f"R{mn} - R{mx}" if mn and mx else str(mn or mx)
                    if title:
                        jobs.append(job_record({
                            "title": title,
                            "company": company,
                            "location": location or "South Africa",
                            "description": desc[:2000],
                            "url": url,
                            "apply_email": _find_email(desc),
                            "platform": "pnet",
                            "salary": salary_raw,
                            "job_type": item.get("employmentType", ""),
                        }))
        except Exception:
            pass
    return jobs


def _collect_listing_links(keywords, max_pages=50):
    query = keywords.strip().replace(" ", "-").lower()
    seen = set()
    links = []
    session = requests.Session()

    url_patterns = [
        f"{BASE}/jobs/{query}/",
        f"{BASE}/jobs/?keywords={keywords.replace(' ', '+')}",
        f"{BASE}/jobs/{query.replace('-', '%20')}/",
    ]

    for base_url in url_patterns:
        for pg in range(1, max_pages + 1):
            session.headers.update(random_headers())
            url = base_url if pg == 1 else f"{base_url}?page={pg}" if "?" not in base_url else f"{base_url}&page={pg}"
            try:
                r = session.get(url, timeout=20)
                soup = BeautifulSoup(r.text, "html.parser")

                # collect detail page links
                found = []
                for a in soup.find_all("a", href=re.compile(r"/jobs/[^/]+-\d+/?$")):
                    href = a["href"]
                    full = href if href.startswith("http") else BASE + href
                    key = full.split("?")[0]
                    if key not in seen and key != f"{BASE}/jobs/":
                        seen.add(key)
                        found.append(key)

                if not found:
                    break
                links.extend(found)
                print(f"[PNet] Page {pg}: {len(found)} links (total: {len(links)})")
                page_delay()
            except Exception as e:
                print(f"[PNet] Page {pg} error: {e}")
                break

        if links:
            break

    return links


def _scrape_detail(url):
    try:
        r = requests.get(url, headers=random_headers(), timeout=20)
        r.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    raw_text = soup.get_text(separator="\n", strip=True)

    # try JSON-LD first
    ld_jobs = _try_json_ld(soup)
    if ld_jobs:
        j = ld_jobs[0]
        j["url"] = url
        return j

    selector_sets = [
        ("article.job-card", "h2,h3,.job-title,[data-testid='job-title']", ".company,[data-testid='company-name'],.employer"),
        ("[data-job-id]", "h2,h3,.title", ".company,.employer"),
        (".job-item", "h2,h3,a", ".company,.employer"),
        ("article", "h2,h3", ".company,.employer"),
        ("[class*='JobCard']", "[class*='title']", "[class*='company'],[class*='employer']"),
    ]

    title = company = ""
    for card_sel, title_sel, company_sel in selector_sets:
        card = soup.select_one(card_sel)
        if not card:
            continue
        title_el = card.select_one(title_sel)
        company_el = card.select_one(company_sel)
        title = title_el.get_text(strip=True) if title_el else ""
        company = company_el.get_text(strip=True) if company_el else ""
        if title:
            break

    if not title:
        h1 = soup.select_one("h1")
        title = h1.get_text(strip=True) if h1 else ""
    if not title:
        return None

    salary_m = re.search(r'(R\s?[\d ,]+(?:\s*[-–]\s*R\s?[\d ,]+)?|Market Related|Negotiable)', raw_text, re.I)
    salary = salary_m.group(0).strip() if salary_m else ""

    job_type_m = re.search(r'(Permanent|Contract|Temporary|Internship|Learnership|Part.time|Full.time)', raw_text, re.I)
    job_type = job_type_m.group(0).strip() if job_type_m else ""

    location_m = re.search(r'(?:Location|City)[:\s]+([^\n]+)', raw_text, re.I)
    location = location_m.group(1).strip() if location_m else "South Africa"

    desc_el = soup.select_one("[class*='description'], article, main, [class*='job-detail']")
    description = desc_el.get_text(separator="\n", strip=True)[:2000] if desc_el else ""

    how_to_apply_m = re.search(r'(?:How to Apply|To Apply|Application Process)[:\s]*([^\n]{10,300})', raw_text, re.I)
    how_to_apply = how_to_apply_m.group(1).strip() if how_to_apply_m else ""

    return job_record({
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "url": url,
        "apply_email": _find_email(description) or _find_email(raw_text),
        "platform": "pnet",
        "salary": salary,
        "job_type": job_type,
        "how_to_apply": how_to_apply,
        "raw_text": raw_text[:3000],
    })


def scrape_pnet(keywords="developer", limit=500):
    # First try JSON-LD from listing pages (fast bulk path)
    query = keywords.strip().replace(" ", "-").lower()
    bulk_jobs = []
    seen_titles = set()
    session = requests.Session()

    listing_urls = [
        f"{BASE}/jobs/{query}/",
        f"{BASE}/jobs/?keywords={keywords.replace(' ', '+')}",
    ]

    for base_url in listing_urls:
        for pg in range(1, 51):
            session.headers.update(random_headers())
            url = base_url if pg == 1 else (f"{base_url}?page={pg}" if "?" not in base_url else f"{base_url}&page={pg}")
            try:
                r = session.get(url, timeout=20)
                soup = BeautifulSoup(r.text, "html.parser")
                ld_jobs = _try_json_ld(soup)
                new = [j for j in ld_jobs if j["title"] not in seen_titles]
                for j in new:
                    seen_titles.add(j["title"])
                if not new and pg > 1:
                    break
                bulk_jobs.extend(new)
                print(f"[PNet] JSON-LD page {pg}: +{len(new)} jobs (total: {len(bulk_jobs)})")
                if len(bulk_jobs) >= limit:
                    break
                page_delay()
            except Exception as e:
                print(f"[PNet] Listing page {pg} error: {e}")
                break
        if len(bulk_jobs) >= limit:
            break

    if bulk_jobs:
        print(f"[PNet] Fast path: {len(bulk_jobs)} jobs via JSON-LD")
        return bulk_jobs[:limit]

    # Fallback: scrape detail pages individually
    print("[PNet] JSON-LD empty, falling back to detail scraping...")
    links = _collect_listing_links(keywords, max_pages=50)
    if not links:
        print("[PNet] No links found")
        return []

    from apps.scraper.scrapers.async_http import parallel_fetch
    jobs = parallel_fetch(links[:limit], _scrape_detail, max_workers=16)
    jobs = [j for j in jobs if j and j.get("title")]
    print(f"[PNet] Detail scrape: {len(jobs)} jobs")
    return jobs
