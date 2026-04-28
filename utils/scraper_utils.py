import re
import random
import time

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0",
]

ACCEPT_LANGS = [
    "en-ZA,en;q=0.9,af;q=0.8",
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
    "en-ZA,en-US;q=0.9,en;q=0.8",
]


def random_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": random.choice(ACCEPT_LANGS),
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    }


def polite_delay(min_s=0.8, max_s=2.5):
    time.sleep(random.uniform(min_s, max_s))


def page_delay():
    time.sleep(random.uniform(1.5, 4.0))


def parse_salary_range(salary_str: str):
    if not salary_str:
        return 0, 0
    nums = re.findall(r'[\d]{4,7}', salary_str.replace(",", "").replace(" ", ""))
    clean = [int(n) for n in nums if 1000 <= int(n) <= 9999999]
    if len(clean) >= 2:
        return min(clean[:2]), max(clean[:2])
    elif len(clean) == 1:
        return clean[0], clean[0]
    return 0, 0


def extract_requirements(text: str) -> list:
    if not text:
        return []
    lines = text.split("\n")
    out = []
    in_section = False
    for line in lines:
        line = line.strip()
        if re.search(r'^(REQUIREMENTS?|QUALIFICATIONS?|MINIMUM REQUIREMENTS?)\s*[:\-]?\s*$', line, re.I):
            in_section = True
            continue
        if re.search(r'^(DUTIES|RESPONSIBILITIES|HOW TO APPLY|APPLICATIONS?|ENQUIRIES?)\s*[:\-]?\s*$', line, re.I):
            in_section = False
        if in_section and len(line) > 10:
            out.append(re.sub(r'^[-•*·▪➢➤►]\s*', '', line))
        elif re.search(r'(require|must have|minimum|matric|degree|diploma|certificate|years.*experience|experience.*years|NQF|proficien|familiar)', line, re.I) and len(line) > 15:
            out.append(re.sub(r'^[-•*·▪➢➤►]\s*', '', line))
    return list(dict.fromkeys(out))[:15]


def extract_duties(text: str) -> list:
    if not text:
        return []
    lines = text.split("\n")
    out = []
    in_section = False
    for line in lines:
        line = line.strip()
        if re.search(r'^(DUTIES|KEY RESPONSIBILITIES?|RESPONSIBILITIES?|KEY OUTPUTS?)\s*[:\-]?\s*$', line, re.I):
            in_section = True
            continue
        if re.search(r'^(REQUIREMENTS?|QUALIFICATIONS?|HOW TO APPLY|APPLICATIONS?|CLOSING)\s*[:\-]?\s*$', line, re.I):
            in_section = False
        if in_section and len(line) > 10:
            out.append(re.sub(r'^[-•*·▪➢➤►]\s*', '', line))
    return list(dict.fromkeys(out))[:15]


def job_record(overrides: dict) -> dict:
    base = {
        "title": "",
        "company": "",
        "location": "",
        "salary": "",
        "salary_min": 0,
        "salary_max": 0,
        "job_type": "",
        "closing_date": "",
        "apply_email": "",
        "phone": "",
        "requirements": [],
        "duties": [],
        "how_to_apply": "",
        "docs_required": "",
        "url": "",
        "platform": "",
        "description": "",
        "raw_text": "",
    }
    base.update(overrides)

    if base["salary"] and not base["salary_min"]:
        base["salary_min"], base["salary_max"] = parse_salary_range(base["salary"])

    if not base["requirements"] and base["description"]:
        base["requirements"] = extract_requirements(base["description"])

    if not base["duties"] and base["description"]:
        base["duties"] = extract_duties(base["description"])

    return base
