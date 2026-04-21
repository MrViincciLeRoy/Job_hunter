"""
Government job scrapers for South African public service vacancies.
Sources: DPSA, SAYouth, ESSA, Gov.za
"""
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-ZA,en;q=0.9",
}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
SKIP_EMAILS = {"noreply", "no-reply", "donotreply", "webmaster", "admin", "privacy", "legal", "info@dpsa"}


def _find_email(text: str) -> str:
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower()
        if not any(s in e for s in SKIP_EMAILS):
            return m.group(0)
    return ""


# ── DPSA ────────────────────────────────────────────────────────────────────

def scrape_dpsa(keywords: str = None, limit: int = 30) -> list:
    """
    Scrapes DPSA vacancy circulars from dpsa.gov.za/newsroom/psvc
    These are PDF links — we grab the circular index and extract job entries.
    """
    base = "https://www.dpsa.gov.za"
    url = "https://www.dpsa.gov.za/newsroom/psvc"
    jobs = []

    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        # Find the most recent circular links
        circular_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            # DPSA circulars are typically labeled "Circular X of YYYY"
            if re.search(r"circular|vacancy|psvc", text, re.IGNORECASE) or \
               re.search(r"circular|psvc", href, re.IGNORECASE):
                full = href if href.startswith("http") else urljoin(base, href)
                circular_links.append((text, full))

        # Also look for direct job listing items on the page
        items = soup.select("li, .vacancy-item, article, .post, tr")
        for item in items[:50]:
            text = item.get_text(separator=" ", strip=True)
            if len(text) < 20:
                continue
            link_el = item.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            job_url = href if href.startswith("http") else urljoin(base, href)
            title_match = re.search(r"(post|position|vacancy|ref[:\s]+\w+)", text, re.IGNORECASE)
            if title_match or (link_el and len(text) > 30):
                title = link_el.get_text(strip=True) if link_el else text[:80]
                email = _find_email(text)
                if title and len(title) > 5:
                    jobs.append({
                        "title": title, "company": "South African Government",
                        "location": "South Africa", "description": text[:600],
                        "url": job_url, "apply_email": email,
                        "platform": "dpsa",
                    })

        # Fetch the most recent circular page for actual job entries
        if circular_links and len(jobs) < 5:
            _, latest_url = circular_links[0]
            try:
                cr = requests.get(latest_url, headers=HEADERS, timeout=20)
                csoup = BeautifulSoup(cr.text, "html.parser")
                rows = csoup.select("tr, li, .vacancy, article")
                for row in rows[:60]:
                    rt = row.get_text(separator=" ", strip=True)
                    if len(rt) < 15:
                        continue
                    link_el = row.select_one("a[href]")
                    href = link_el["href"] if link_el else ""
                    job_url = href if href.startswith("http") else urljoin(latest_url, href)
                    email = _find_email(rt)
                    ref = re.search(r"ref(?:erence)?[:\s#]*([A-Z0-9/\-]+)", rt, re.IGNORECASE)
                    title = link_el.get_text(strip=True) if link_el else rt[:80]
                    if title and len(title) > 5:
                        jobs.append({
                            "title": title,
                            "company": "DPSA – " + (ref.group(1) if ref else "Government"),
                            "location": "South Africa", "description": rt[:600],
                            "url": job_url, "apply_email": email,
                            "platform": "dpsa",
                        })
            except Exception as e:
                print(f"[DPSA] Circular fetch error: {e}")

    except Exception as e:
        print(f"[DPSA] Error: {e}")

    # Filter by keywords if given
    if keywords:
        kws = keywords.lower().split()
        jobs = [j for j in jobs if any(kw in j["title"].lower() or kw in j["description"].lower() for kw in kws)]

    # Deduplicate
    seen, out = set(), []
    for j in jobs:
        key = j["title"].lower()[:50]
        if key not in seen:
            seen.add(key)
            out.append(j)

    return out[:limit]


# ── SAYouth ─────────────────────────────────────────────────────────────────

def scrape_sayouth(keywords: str = None, limit: int = 30) -> list:
    """
    Scrapes SAYouth.mobi for youth/entry-level opportunities.
    Zero-rated site — great for learnerships and PYEI roles.
    """
    base = "https://sayouth.mobi"
    jobs = []

    urls = [
        f"{base}/Jobs",
        f"{base}/Opportunities",
        f"{base}/jobs",
    ]
    if keywords:
        q = keywords.replace(" ", "+")
        urls.insert(0, f"{base}/Jobs?search={q}")

    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")

            cards = soup.select(
                ".job-card, .opportunity-card, article, .listing, "
                "[class*='job'], [class*='opportunity'], li.result, .card"
            )

            for card in cards[:limit]:
                title_el = card.select_one("h2, h3, h4, .title, [class*='title'], a")
                company_el = card.select_one(".company, .employer, .organisation, [class*='company']")
                location_el = card.select_one(".location, .area, [class*='location']")
                link_el = card.select_one("a[href]")

                title = title_el.get_text(strip=True) if title_el else ""
                if not title or len(title) < 4:
                    continue

                company = company_el.get_text(strip=True) if company_el else "SA Youth"
                location = location_el.get_text(strip=True) if location_el else "South Africa"
                href = link_el["href"] if link_el else ""
                job_url = href if href.startswith("http") else urljoin(base, href)
                text = card.get_text(separator=" ", strip=True)
                email = _find_email(text)

                jobs.append({
                    "title": title, "company": company,
                    "location": location, "description": text[:600],
                    "url": job_url, "apply_email": email,
                    "platform": "sayouth",
                })

            if jobs:
                break

        except Exception as e:
            print(f"[SAYouth] Error on {url}: {e}")

    if keywords:
        kws = keywords.lower().split()
        jobs = [j for j in jobs if any(kw in j["title"].lower() or kw in j["description"].lower() for kw in kws)]

    return jobs[:limit]


# ── ESSA ─────────────────────────────────────────────────────────────────────

def scrape_essa(keywords: str = None, limit: int = 30) -> list:
    """
    Scrapes ESSA (Employment Services of SA) — labour.gov.za portal.
    """
    base = "https://essa.labour.gov.za"
    jobs = []

    urls = [f"{base}/home/opportunities"]
    if keywords:
        q = keywords.replace(" ", "+")
        urls.insert(0, f"{base}/home/search?query={q}")

    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")

            cards = soup.select(
                ".job, .vacancy, article, .listing, .opportunity, "
                "[class*='job'], [class*='vacancy'], tr, li.result"
            )

            for card in cards[:limit]:
                title_el = card.select_one("h2, h3, h4, .title, a, [class*='title']")
                company_el = card.select_one(".company, .employer, .department, [class*='company']")
                location_el = card.select_one(".location, .province, [class*='location']")
                link_el = card.select_one("a[href]")

                title = title_el.get_text(strip=True) if title_el else ""
                if not title or len(title) < 4:
                    continue

                company = company_el.get_text(strip=True) if company_el else "Department of Labour"
                location = location_el.get_text(strip=True) if location_el else "South Africa"
                href = link_el["href"] if link_el else ""
                job_url = href if href.startswith("http") else urljoin(base, href)
                text = card.get_text(separator=" ", strip=True)
                email = _find_email(text)

                jobs.append({
                    "title": title, "company": company,
                    "location": location, "description": text[:600],
                    "url": job_url, "apply_email": email,
                    "platform": "essa",
                })

            if jobs:
                break

        except Exception as e:
            print(f"[ESSA] Error on {url}: {e}")

    return jobs[:limit]


# ── Gov.za Jobs Portal ────────────────────────────────────────────────────────

def scrape_govza(keywords: str = None, limit: int = 30) -> list:
    """
    Scrapes the Gov.za central jobs portal and linked department vacancy pages.
    """
    base = "https://www.gov.za"
    jobs = []
    dept_urls_scraped = set()

    try:
        r = requests.get("https://www.gov.za/about-government/government-jobs", headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        # Collect department vacancy links
        dept_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if any(kw in text.lower() or kw in href.lower() for kw in ("vacanc", "jobs", "career", "employm")):
                full = href if href.startswith("http") else urljoin(base, href)
                dept_links.append((text, full))

        # Also grab any job listings directly on this page
        for item in soup.select("li, article, .field-item, .views-row"):
            text = item.get_text(separator=" ", strip=True)
            if len(text) < 15:
                continue
            link_el = item.select_one("a[href]")
            if not link_el:
                continue
            title = link_el.get_text(strip=True)
            href = link_el["href"]
            job_url = href if href.startswith("http") else urljoin(base, href)
            email = _find_email(text)
            if title and len(title) > 5:
                jobs.append({
                    "title": title, "company": "South African Government",
                    "location": "South Africa", "description": text[:600],
                    "url": job_url, "apply_email": email,
                    "platform": "govza",
                })

        # Follow top 5 department links
        for dept_name, dept_url in dept_links[:5]:
            if dept_url in dept_urls_scraped:
                continue
            dept_urls_scraped.add(dept_url)
            try:
                dr = requests.get(dept_url, headers=HEADERS, timeout=15)
                dsoup = BeautifulSoup(dr.text, "html.parser")
                for item in dsoup.select("li, article, tr, .vacancy, .job, [class*='job']"):
                    text = item.get_text(separator=" ", strip=True)
                    if len(text) < 20:
                        continue
                    link_el = item.select_one("a[href]")
                    title = link_el.get_text(strip=True) if link_el else text[:80]
                    href = link_el["href"] if link_el else ""
                    job_url = href if href.startswith("http") else urljoin(dept_url, href)
                    email = _find_email(text)
                    if title and len(title) > 5:
                        jobs.append({
                            "title": title, "company": dept_name or "SA Government Dept",
                            "location": "South Africa", "description": text[:600],
                            "url": job_url, "apply_email": email,
                            "platform": "govza",
                        })
            except Exception:
                pass

    except Exception as e:
        print(f"[GovZA] Error: {e}")

    # Filter by keywords
    if keywords:
        kws = keywords.lower().split()
        jobs = [j for j in jobs if any(kw in j["title"].lower() or kw in j["description"].lower() for kw in kws)]

    # Deduplicate
    seen, out = set(), []
    for j in jobs:
        key = j["title"].lower()[:50]
        if key not in seen:
            seen.add(key)
            out.append(j)

    return out[:limit]
