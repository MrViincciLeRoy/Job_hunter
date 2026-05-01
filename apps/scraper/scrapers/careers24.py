import re
import json
import time
import random
import requests
from bs4 import BeautifulSoup
from utils.scraper_utils import (
    random_headers, polite_delay, page_delay, job_record,
    extract_email_priority, extract_closing_date,
)
from apps.scraper.scrapers.async_http import parallel_fetch

BASE_URL = "https://www.careers24.com"
_PAGE_SIZE = 10


def _clean(t):
    return re.sub(r"\s+", " ", t or "").strip()


def _is_real_listing_page(html: str) -> bool:
    """Return True if the page looks like a real Careers24 listing (not a bot-challenge/empty page)."""
    return (
        'id="SearchResults"' in html
        and '/jobs/adverts/' in html
        and 'var vsp' in html
    )


def _warm_session(session: requests.Session) -> bool:
    """
    Visit the homepage first so Careers24 sets cookies and sees a Referer on
    subsequent requests. A cold requests.Session with no cookies is the #1 bot
    signal. Returns True if the warm-up succeeded.
    """
    try:
        session.headers.update({
            **random_headers(),
            "Referer": "https://www.google.com/",
        })
        r = session.get(f"{BASE_URL}/", timeout=20)
        r.raise_for_status()
        # Give the server a human-feeling pause
        time.sleep(random.uniform(2.0, 4.5))
        return True
    except Exception as e:
        print(f"[Careers24] Session warm-up failed: {e}")
        return False


def _get_page(session: requests.Session, url: str, referer: str, max_retries: int = 3):
    """
    Fetch a listing page with Referer set and retry on bot-detection or errors.
    Returns (response_text, soup) or (None, None) after all retries exhausted.
    """
    for attempt in range(1, max_retries + 1):
        try:
            session.headers.update({
                **random_headers(),
                "Referer": referer,
            })
            r = session.get(url, timeout=30)
            r.raise_for_status()

            html = r.text

            # Bot-challenge / empty page detection
            if not _is_real_listing_page(html):
                print(
                    f"[Careers24] Attempt {attempt}/{max_retries}: "
                    f"bot-challenge or empty response detected at {url}"
                )
                if attempt < max_retries:
                    backoff = random.uniform(8.0, 20.0) * attempt
                    print(f"[Careers24] Backing off {backoff:.1f}s before retry?")
                    time.sleep(backoff)
                    # Re-warm the session between retries
                    _warm_session(session)
                continue

            return html, BeautifulSoup(html, "html.parser")

        except Exception as e:
            print(f"[Careers24] Attempt {attempt}/{max_retries} error at {url}: {e}")
            if attempt < max_retries:
                time.sleep(random.uniform(5.0, 12.0) * attempt)

    return None, None


def _collect_links(keywords, max_pages=60):
    session = requests.Session()

    # ?? Warm-up: visit homepage first to get cookies + look like a real browser ??
    warmed = _warm_session(session)
    if not warmed:
        print("[Careers24] Warning: session warm-up failed; proceeding anyway")

    seen = set()
    all_links = []

    # Candidate listing URLs ? keyword search first, IT sector fallback, global fallback
    start_urls = []
    if keywords:
        q = keywords.strip().replace(" ", "+")
        start_urls.append(f"{BASE_URL}/jobs/?k={q}&l=south+africa&sort=dateposted")
    start_urls.append(f"{BASE_URL}/jobs/se-it/?sort=dateposted")
    start_urls.append(f"{BASE_URL}/jobs/?sort=dateposted")

    for start_url in start_urls:
        found_on_start = 0
        referer = f"{BASE_URL}/"      # first page looks like it came from the homepage

        for pg in range(1, max_pages + 1):
            if pg == 1:
                url = start_url
            else:
                offset = (pg - 1) * _PAGE_SIZE
                sep = "&" if "?" in start_url else "?"
                url = f"{start_url}{sep}startIndex={offset}"

            html, soup = _get_page(session, url, referer=referer)

            if html is None or soup is None:
                print(f"[Careers24] Giving up on {start_url} after failed retries at page {pg}")
                break

            found = []
            for a in soup.find_all("a", href=re.compile(r"/jobs/adverts/\d+")):
                href = a["href"]
                full = href if href.startswith("http") else BASE_URL + href
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

            # Each subsequent page uses the previous page as its Referer
            referer = url
            page_delay()

        if all_links:
            break

    if not all_links:
        print(
            "[Careers24] ZERO links collected across all start URLs. "
            "This almost certainly means the runner IP is bot-blocked by Careers24. "
            "Consider adding a residential proxy or switching to a GitHub-hosted runner with a different IP."
        )

    return all_links


def _parse_json_ld(soup):
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

    title_el = soup.select_one("h1")
    title = _clean(title_el.get_text()) if title_el else ""
    if not title:
        return None

    ld = _parse_json_ld(soup)
    ld_company = (ld.get("hiringOrganization") or {}).get("name", "")
    ld_job_type = ld.get("employmentType", "")
    ld_closing = ld.get("validThrough", "")[:10]

    company = ld_company
    if not company:
        emp_p = soup.find("p", string=re.compile(r"Employer", re.I))
        if emp_p:
            strong = emp_p.find("strong")
            company = _clean(strong.get_text()) if strong else ""
    if not company:
        emp_m = re.search(r"Employer[:\s]+(.+?)(?:\n|$)", text, re.I)
        company = _clean(emp_m.group(1)) if emp_m else ""

    loc_el = soup.select_one('a[href*="/jobs/lc-"]')
    location = _clean(loc_el.get_text()) if loc_el else "South Africa"

    salary = ""
    for li in soup.select("ul.icon-list li"):
        li_text = _clean(li.get_text())
        if "salary" in li_text.lower() or "remuneration" in li_text.lower():
            salary = re.sub(r"^salary\s*[:\s]+", "", li_text, flags=re.I).strip()
            break
    if not salary:
        sal_m = re.search(
            r"(?:BASIC SALARY|Salary|Remuneration|Package)[:\s]*([^\n<]{3,80})",
            text, re.I
        )
        salary = _clean(sal_m.group(1)) if sal_m else ""

    job_type = ""
    for li in soup.select("ul.icon-list li"):
        li_text = _clean(li.get_text())
        if "job type" in li_text.lower():
            job_type = re.sub(r"^job\s+type\s*[:\s]+", "", li_text, flags=re.I).strip()
            break
    if not job_type and ld_job_type:
        job_type = ld_job_type.replace("_", "-").title()
    if not job_type:
        jt_m = re.search(
            r"(?:Job Type|Contract Type|Employment Type)[:\s]*([^\n]{3,50})", text, re.I
        )
        job_type = _clean(jt_m.group(1)) if jt_m else ""

    descrip_divs = soup.select(".v-descrip")
    if descrip_divs:
        description = "\n\n".join(
            _clean(d.get_text(separator="\n")) for d in descrip_divs
        )
    else:
        main_el = soup.select_one("[class*='c24-vacancy-details'], article, main")
        description = _clean(main_el.get_text("\n")) if main_el else ""

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