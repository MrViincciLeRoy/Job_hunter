import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote

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

# Sites that virtually never expose emails — skip deep spidering
LOW_EMAIL_DOMAINS = {
    "linkedin.com", "indeed.com", "glassdoor.com", "seek.com",
    "stepstone.com", "monster.com", "reed.co.uk",
}


def _is_low_email_domain(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    return any(d in domain for d in LOW_EMAIL_DOMAINS)


def _clean_emails(emails: list) -> list:
    seen, out = set(), []
    for e in emails:
        e = e.lower().strip().rstrip(".")
        if any(s in e for s in SKIP_EMAILS):
            continue
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def _extract_mailto_emails(html: str) -> list:
    """Pull emails from mailto: href attributes — catches JS-obfuscated ones too."""
    emails = []
    for match in re.finditer(r'mailto:([^"\'?\s>]+)', html, re.IGNORECASE):
        addr = unquote(match.group(1)).split("?")[0].strip()
        if "@" in addr:
            emails.append(addr)
    return emails


def _decode_cloudflare_email(encoded: str) -> str:
    """Cloudflare encodes emails as hex XOR. Decode it."""
    try:
        r = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i+2], 16) ^ r) for i in range(2, len(encoded), 2))
    except Exception:
        return ""


def _extract_cloudflare_emails(soup: BeautifulSoup) -> list:
    emails = []
    for el in soup.select("[data-cfemail]"):
        decoded = _decode_cloudflare_email(el.get("data-cfemail", ""))
        if "@" in decoded:
            emails.append(decoded)
    return emails


def _find_contact_links(soup: BeautifulSoup, base_url: str) -> list:
    urls = []
    keywords = ("contact", "apply", "email us", "reach us", "get in touch", "careers", "vacancy")
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        href = a["href"].lower()
        if any(kw in text or kw in href for kw in keywords):
            full = urljoin(base_url, a["href"])
            if urlparse(full).scheme in ("http", "https") and full != base_url:
                urls.append(full)
    return list(dict.fromkeys(urls))[:3]  # dedupe, max 3


def _scrape_page(url: str, timeout: int = 12) -> dict:
    """Fetch a page and pull every email signal."""
    r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    html = r.text
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)

    emails = (
        EMAIL_RE.findall(text)
        + EMAIL_RE.findall(html)
        + _extract_mailto_emails(html)
        + _extract_cloudflare_emails(soup)
    )
    return {
        "emails": _clean_emails(emails),
        "soup": soup,
        "text": text,
        "html": html,
    }


def spider_url(url: str, timeout: int = 12) -> dict:
    result = {
        "emails": [],
        "phone": "",
        "description": "",
        "requirements": "",
        "raw_url": url,
        "followed_url": None,
        "error": None,
    }

    if not url or not url.startswith("http"):
        result["error"] = "Invalid URL"
        return result

    # Skip sites that never expose emails to avoid wasting time
    if _is_low_email_domain(url):
        result["error"] = "Low-email-likelihood domain — skipped"
        return result

    try:
        page = _scrape_page(url, timeout)
        result["emails"] = page["emails"]

        # Phone (SA format)
        phone_m = re.search(r"(\+27|0)[0-9()\s-]{8,14}", page["text"])
        if phone_m:
            result["phone"] = phone_m.group(0).strip()

        # Description
        for sel in [
            "[class*='description']", "[class*='job-detail']", "[class*='content']",
            "article", "main", ".posting-requirements", "[class*='vacancy']",
        ]:
            el = page["soup"].select_one(sel)
            if el:
                txt = el.get_text(separator="\n", strip=True)
                if len(txt) > 100:
                    result["description"] = txt[:2500]
                    break

        # Requirements block
        req_m = re.search(
            r"(require|must have|minimum|qualification|experience|skills needed)",
            page["text"], re.IGNORECASE,
        )
        if req_m:
            start = max(0, req_m.start() - 50)
            result["requirements"] = page["text"][start:start + 1500]

        # Follow contact/apply pages if no email found yet
        if not result["emails"]:
            for contact_url in _find_contact_links(page["soup"], url):
                result["followed_url"] = contact_url
                try:
                    contact_page = _scrape_page(contact_url, timeout)
                    if contact_page["emails"]:
                        result["emails"] = contact_page["emails"]
                        break
                except Exception:
                    pass

    except requests.exceptions.Timeout:
        result["error"] = "Timeout"
    except requests.exceptions.HTTPError as e:
        result["error"] = f"HTTP {e.response.status_code}"
    except Exception as e:
        result["error"] = str(e)[:120]

    return result


def email_likelihood_score(platform: str, url: str) -> int:
    """
    Rank how likely a job is to yield an email.
    Used to prioritize spider order — higher = spider first.
    """
    if _is_low_email_domain(url):
        return 0
    scores = {
        "pnet": 80,
        "careerjunction": 75,
        "careers24": 70,
        "jobmail": 65,
        "gumtree": 60,
        "indeed": 20,
        "linkedin": 5,
    }
    return scores.get(platform.lower(), 40)
