import re
import json
import time
import requests
from bs4 import BeautifulSoup
from utils.scraper_utils import (
    random_headers, polite_delay, page_delay, job_record,
    extract_email_priority, extract_closing_date,
)
from apps.scraper.scrapers.async_http import parallel_fetch

BASE_URL = "https://www.careers24.com"

# Page size Careers24 actually uses on listing pages
_PAGE_SIZE = 10


def _clean(t):
    return re.sub(r"\s+", " ", t or "").strip()


def _collect_links(keywords, max_pages=60):
    session = requests.Session()
    seen = set()
    all_links = []

    # Build candidate start URLs.
    # FIX 1: Use /jobs/se-it/ (correct IT sector URL ? rmt-incl path is broken/empty).
    # FIX 2: Page size is 10, so pagination offset must use (pg-1)*10, not *20.
    start_urls = []
    if keywords:
        q = keywords.strip().replace(" ", "+")
        start_urls.append(f"{BASE_URL}/jobs/?k={q}&l=south+africa&sort=dateposted")
    # Correct IT sector URL without the broken rmt-incl sub-path
    start_urls.append(f"{BASE_URL}/jobs/se-it/?sort=dateposted")
    start_urls.append(f"{BASE_URL}/jobs/?sort=dateposted")

    for start_url in start_urls:
        session.headers.update(random_headers())
        found_on_start = 0
        for pg in range(1, max_pages + 1):
            # FIX 3: Careers24 listing pages paginate via startIndex query param.
            # Page 1 ? startIndex=0, page 2 ? startIndex=10, etc. (page size = 10).
            if pg == 1:
                url = start_url
            else:
                offset = (pg - 1) * _PAGE_SIZE
                sep = "&" if "?" in start_url else "?"
                url = f"{start_url}{sep}startIndex={offset}"

            try:
                r = session.get(url, timeout=25)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")

                found = []
                # FIX 4: Strip the ?jobindex=N query param from job links before
                # deduplication so the same vacancy isn't fetched twice when it
                # appears on multiple listing pages with different jobindex values.
                for a in soup.find_all("a", href=re.compile(r"/jobs/adverts/\d+")):
                    href = a["href"]
                    full = href if href.startswith("http") else BASE_URL + href
                    # Strip ALL query params ? the clean canonical URL is what we want
                    key = full.split("?")[0].rstrip("/") + "/"
                    m = re.search(r"/adverts/(\d+)-", key)
                    if m and key not in seen:
                        seen.add(key)
                        found.append(key)

                if not found:
                    print(f"[Careers24] No more results at page {pg} ({url})")
                    break

                all_links.extend(found)
                found_on_start += len(found)
                print(
                    f"[Careers24] Page {pg}: {len(found)} links"
                    f" (total so far: {len(all_links)})"
                )
                page_delay()

            except Exception as e:
                print(f"[Careers24] Page {pg} error: {e}")
                break

        if all_links:
            break

    return all_links


def _parse_json_ld(soup):
    """Extract structured data from the page's JSON-LD script block if present."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if data.get("@type") == "JobPosting":
                return data
        except Exception:
            pass
    return {}


def _scrape_detail(url):
    try:
        r = requests.get(url, headers=random_headers(), timeout=20)
        r.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(separator="\n")

    # ?? Title ????????????????????????????????????????????????????????????????
    title_el = soup.select_one("h1")
    title = _clean(title_el.get_text()) if title_el else ""
    if not title:
        return None

    # ?? JSON-LD structured data (most reliable source) ???????????????????????
    ld = _parse_json_ld(soup)
    ld_company = (ld.get("hiringOrganization") or {}).get("name", "")
    ld_job_type = ld.get("employmentType", "")
    ld_closing = ld.get("validThrough", "")[:10]  # ISO date or empty

    # ?? Company ??????????????????????????????????????????????????????????????
    # FIX 5: Company name is inside <strong> within the "Employer:" paragraph,
    # not on a plain text line ? use CSS selector instead of regex on plain text.
    company = ld_company
    if not company:
        emp_p = soup.find("p", string=re.compile(r"Employer", re.I))
        if emp_p:
            strong = emp_p.find("strong")
            company = _clean(strong.get_text()) if strong else ""
    if not company:
        emp_m = re.search(r"Employer[:\s]+(.+?)(?:\n|$)", text, re.I)
        company = _clean(emp_m.group(1)) if emp_m else ""

    # ?? Location ?????????????????????????????????????????????????????????????
    loc_el = soup.select_one('a[href*="/jobs/lc-"]')
    location = _clean(loc_el.get_text()) if loc_el else "South Africa"

    # ?? Salary ???????????????????????????????????????????????????????????????
    # FIX 6: Salary is embedded in HTML as "R 19 000 - R 24 000" inside a <li>
    # that contains "Salary:" ? scrape the element text, not a regex on raw text.
    salary = ""
    for li in soup.select("ul.icon-list li"):
        li_text = _clean(li.get_text())
        if "salary" in li_text.lower() or "remuneration" in li_text.lower():
            # Strip the label prefix ("Salary: Market Related" ? "Market Related")
            salary = re.sub(r"^salary\s*[:\s]+", "", li_text, flags=re.I).strip()
            break
    if not salary:
        sal_m = re.search(
            r"(?:BASIC SALARY|Salary|Remuneration|Package)[:\s]*([^\n<]{3,80})",
            text, re.I
        )
        salary = _clean(sal_m.group(1)) if sal_m else ""

    # ?? Job type ?????????????????????????????????????????????????????????????
    # FIX 7: JSON-LD gives us employment type (FULL_TIME etc); also check <li> text.
    job_type = ""
    for li in soup.select("ul.icon-list li"):
        li_text = _clean(li.get_text())
        if "job type" in li_text.lower():
            job_type = re.sub(r"^job\s+type\s*[:\s]+", "", li_text, flags=re.I).strip()
            break
    if not job_type and ld_job_type:
        # Normalise JSON-LD value (FULL_TIME ? Full-time)
        job_type = ld_job_type.replace("_", "-").title()
    if not job_type:
        jt_m = re.search(
            r"(?:Job Type|Contract Type|Employment Type)[:\s]*([^\n]{3,50})", text, re.I
        )
        job_type = _clean(jt_m.group(1)) if jt_m else ""

    # ?? Description ??????????????????????????????????????????????????????????
    # FIX 8: Careers24 places the full job description inside .v-descrip divs.
    # Extracting from those elements preserves bullet structure better than
    # trying to regex-parse the raw plain-text dump.
    descrip_divs = soup.select(".v-descrip")
    if descrip_divs:
        description = "\n\n".join(
            _clean(d.get_text(separator="\n")) for d in descrip_divs
        )
    else:
        # Fallback: main content area
        main_el = soup.select_one("[class*='c24-vacancy-details'], article, main")
        description = _clean(main_el.get_text("\n")) if main_el else ""

    # ?? Requirements & duties from description ???????????????????????????????
    req_m = re.search(
        r"(?:Minimum\s+Requirements?|Requirements?|Qualifications?)[:\s]*\n+(.*?)"
        r"(?:\n{2,}|Knowledge|Skills|Salary|$)",
        description, re.DOTALL | re.I,
    )
    requirements = _clean(req_m.group(1))[:600] if req_m else ""

    duties_m = re.search(
        r"(?:Duties\s+(?:and\s+)?Responsibilities|Key\s+Responsibilities?|Responsibilities)[:\s]*\n+(.*?)"
        r"(?:\n{2,}|Minimum\s+Requirements?|Requirements?|Skills|Salary|$)",
        description, re.DOTALL | re.I,
    )
    duties = _clean(duties_m.group(1))[:600] if duties_m else ""

    # ?? How to apply / email ?????????????????????????????????????????????????
    apply_m = re.search(
        r"(?:How\s+to\s+Apply|To\s+Apply|Application\s+Process|"
        r"Send.*?CV|Apply.*?via)[:\s]*([^\n]{10,200})",
        text, re.I,
    )
    how_to_apply = _clean(apply_m.group(1)) if apply_m else ""

    apply_email = extract_email_priority(
        how_to_apply=how_to_apply,
        description=description,
        raw_text=text,
    )

    # ?? Closing date ?????????????????????????????????????????????????????????
    # Prefer JSON-LD validThrough, fall back to text extraction
    closing_date = ld_closing or extract_closing_date(text)

    return job_record({
        "title":        title,
        "company":      company,
        "location":     location,
        "description":  description[:2000],
        "url":          url,
        "apply_email":  apply_email,
        "platform":     "careers24",
        "salary":       salary,
        "job_type":     job_type,
        "closing_date": closing_date,
        "how_to_apply": how_to_apply,
        "raw_text":     text[:3000],
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