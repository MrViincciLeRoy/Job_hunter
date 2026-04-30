try:
    import aiohttp
except ImportError:
    aiohttp = None

import re
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote
from .async_http import run_async

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
SKIP_EMAILS = {
    "noreply", "no-reply", "donotreply", "support", "info", "hello",
    "admin", "careers@linkedin", "jobs@indeed", "privacy", "legal",
    "news", "newsletter", "unsubscribe", "webmaster", "postmaster",
}
LOW_EMAIL_DOMAINS = {
    "linkedin.com", "indeed.com", "glassdoor.com", "seek.com",
    "stepstone.com", "monster.com", "reed.co.uk",
}


def _is_low_email_domain(url):
    domain = urlparse(url).netloc.lower()
    return any(d in domain for d in LOW_EMAIL_DOMAINS)


def _clean_emails(emails):
    seen, out = set(), []
    for e in emails:
        e = e.lower().strip().rstrip(".")
        if any(s in e for s in SKIP_EMAILS):
            continue
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def _extract_mailto_emails(html):
    emails = []
    for match in re.finditer(r'mailto:([^"\'?\s>]+)', html, re.IGNORECASE):
        addr = unquote(match.group(1)).split("?")[0].strip()
        if "@" in addr:
            emails.append(addr)
    return emails


def _decode_cloudflare_email(encoded):
    try:
        r = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i+2], 16) ^ r) for i in range(2, len(encoded), 2))
    except Exception:
        return ""


def _parse_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)

    cf_emails = [_decode_cloudflare_email(el.get("data-cfemail", ""))
                 for el in soup.select("[data-cfemail]") if el.get("data-cfemail")]

    emails = _clean_emails(
        EMAIL_RE.findall(text)
        + EMAIL_RE.findall(html)
        + _extract_mailto_emails(html)
        + cf_emails
    )

    phone_m = re.search(r"(\+27|0)[0-9()\s-]{8,14}", text)
    phone = phone_m.group(0).strip() if phone_m else ""

    description = ""
    for sel in ["[class*='description']", "[class*='job-detail']", "article", "main", "[class*='vacancy']"]:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(separator="\n", strip=True)
            if len(txt) > 100:
                description = txt[:2500]
                break

    contact_links = []
    for a in soup.find_all("a", href=True):
        t = a.get_text(strip=True).lower()
        h = a["href"].lower()
        if any(kw in t or kw in h for kw in ("contact", "apply", "email us", "careers", "vacancy")):
            full = urljoin(url, a["href"])
            if urlparse(full).scheme in ("http", "https") and full != url:
                contact_links.append(full)

    return {
        "emails": emails,
        "phone": phone,
        "description": description,
        "contact_links": list(dict.fromkeys(contact_links))[:3],
        "soup": soup,
    }


async def _async_spider(url, session, timeout=12):
    result = {"emails": [], "phone": "", "description": "", "followed_url": None, "error": None, "raw_url": url}

    if aiohttp is None:
        result["error"] = "aiohttp not installed"
        return result

    if not url or not url.startswith("http"):
        result["error"] = "Invalid URL"
        return result

    if _is_low_email_domain(url):
        result["error"] = "Low-email-likelihood domain — skipped"
        return result

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            r.raise_for_status()
            html = await r.text(errors="replace")
    except asyncio.TimeoutError:
        result["error"] = "Timeout"
        return result
    except aiohttp.ClientResponseError as e:
        result["error"] = f"HTTP {e.status}"
        return result
    except Exception as e:
        result["error"] = str(e)[:120]
        return result

    parsed = _parse_page(html, url)
    result["emails"] = parsed["emails"]
    result["phone"] = parsed["phone"]
    result["description"] = parsed["description"]

    if not result["emails"] and parsed["contact_links"]:
        for contact_url in parsed["contact_links"]:
            try:
                async with session.get(contact_url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                    r.raise_for_status()
                    chtml = await r.text(errors="replace")
                    cparsed = _parse_page(chtml, contact_url)
                    if cparsed["emails"]:
                        result["emails"] = cparsed["emails"]
                        result["followed_url"] = contact_url
                        break
            except Exception:
                pass

    return result


async def _spider_many_async(urls, timeout=12, max_concurrent=15):
    if aiohttp is None:
        return {url: {"emails": [], "phone": "", "description": "", "error": "aiohttp not installed"} for url in urls}

    sem = asyncio.Semaphore(max_concurrent)
    connector = aiohttp.TCPConnector(limit=max_concurrent, ssl=False)
    results = {}

    async def _bounded(url):
        async with sem:
            results[url] = await _async_spider(url, session, timeout)

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        await asyncio.gather(*[_bounded(u) for u in urls])

    return results


def spider_url(url, timeout=12):
    return run_async(_async_spider_single(url, timeout))


async def _async_spider_single(url, timeout):
    if aiohttp is None:
        return {"emails": [], "phone": "", "description": "", "error": "aiohttp not installed"}
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        return await _async_spider(url, session, timeout)


def spider_many(urls, timeout=12, max_concurrent=15):
    return run_async(_spider_many_async(urls, timeout, max_concurrent))


def email_likelihood_score(platform, url):
    if _is_low_email_domain(url):
        return 0
    scores = {
        "pnet": 80, "careerjunction": 75, "careers24": 70,
        "jobmail": 65, "gumtree": 60, "indeed": 20, "linkedin": 5,
    }
    return scores.get(platform.lower(), 40)