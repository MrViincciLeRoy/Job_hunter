import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
SKIP_EMAILS = {"noreply", "no-reply", "donotreply", "support", "info", "contact", "hello", "admin", "careers@linkedin", "jobs@indeed"}


def _clean_emails(emails: list) -> list:
    out = []
    for e in emails:
        e = e.lower().strip()
        if any(s in e for s in SKIP_EMAILS):
            continue
        if e not in out:
            out.append(e)
    return out


def _find_emails_in_text(text: str) -> list:
    return EMAIL_RE.findall(text)


def _find_contact_link(soup: BeautifulSoup, base_url: str) -> str | None:
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        href = a["href"].lower()
        if any(kw in text or kw in href for kw in ("contact", "apply", "email")):
            full = urljoin(base_url, a["href"])
            if urlparse(full).scheme in ("http", "https"):
                return full
    return None


def spider_url(url: str, follow_contact: bool = True, timeout: int = 12) -> dict:
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

    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        page_text = soup.get_text(separator=" ", strip=True)

        emails = _find_emails_in_text(page_text)
        emails += _find_emails_in_text(r.text)  # catch obfuscated mailto: in raw html
        result["emails"] = _clean_emails(emails)

        phone_match = re.search(r"(\+27|0)[0-9()\s-]{8,14}", page_text)
        if phone_match:
            result["phone"] = phone_match.group(0).strip()

        for sel in [
            "[class*='description']", "[class*='job-detail']",
            "[class*='content']", "article", "main", ".posting-requirements",
        ]:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(separator="\n", strip=True)
                if len(txt) > 100:
                    result["description"] = txt[:2000]
                    break

        req_keywords = r"(require|must have|minimum|qualification|experience|skills needed)"
        req_match = re.search(req_keywords, page_text, re.IGNORECASE)
        if req_match:
            start = max(0, req_match.start() - 50)
            result["requirements"] = page_text[start:start + 1200]

        # follow contact/apply page if no email found
        if not result["emails"] and follow_contact:
            contact_url = _find_contact_link(soup, url)
            if contact_url and contact_url != url:
                result["followed_url"] = contact_url
                try:
                    r2 = requests.get(contact_url, headers=HEADERS, timeout=timeout)
                    soup2 = BeautifulSoup(r2.text, "html.parser")
                    more_emails = _find_emails_in_text(soup2.get_text() + r2.text)
                    result["emails"] = _clean_emails(more_emails)
                except Exception:
                    pass

    except requests.exceptions.Timeout:
        result["error"] = "Timeout"
    except requests.exceptions.HTTPError as e:
        result["error"] = f"HTTP {e.response.status_code}"
    except Exception as e:
        result["error"] = str(e)[:120]

    return result
