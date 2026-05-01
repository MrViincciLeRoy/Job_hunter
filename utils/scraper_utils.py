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
        elif re.search(
            r'(require|must have|minimum|matric|degree|diploma|certificate|years.*experience|experience.*years|NQF|proficien|familiar)',
            line, re.I
        ) and len(line) > 15:
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


# ─── Email extraction ─────────────────────────────────────────────────────────

_EMAIL_RE_UTIL = re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}')

_SKIP_EMAIL_FRAGMENTS = {
    'noreply', 'no-reply', 'donotreply', 'unsubscribe',
    'webmaster', 'postmaster', 'privacy', 'legal',
    'info@jobmail', 'info@gumtree', 'info@careerjunction',
    'info@careers24', 'info@pnet', 'support@', 'help@',
    'admin@', 'news@', 'newsletter@', 'gdpr@', 'dpo@',
}

_HOW_TO_APPLY_HEADERS_RE = re.compile(
    r'(?:how\s+to\s+apply|to\s+apply|application\s+process|send\s+(?:your\s+)?(?:cv|resume)|'
    r'forward\s+(?:your\s+)?(?:cv|resume)|email\s+(?:your\s+)?(?:cv|resume)|'
    r'applications?\s+to|enquiries?|contact\s+us|apply\s+(?:via|by|to))',
    re.IGNORECASE,
)

_CLOSING_HEADERS_RE = re.compile(
    r'(?:closing\s+date|application\s+deadline|deadline|close\s+date|'
    r'applications?\s+close|last\s+date\s+to\s+apply|apply\s+by|submit\s+by)[:\s]*',
    re.IGNORECASE,
)

_MONTH_NAMES_PAT = (
    r'jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
    r'jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?'
)

_DATE_PATTERNS_UTIL = [
    re.compile(rf'(\d{{1,2}})\s+({_MONTH_NAMES_PAT}),?\s+(\d{{4}})', re.IGNORECASE),
    re.compile(rf'({_MONTH_NAMES_PAT})\s+(\d{{1,2}}),?\s+(\d{{4}})', re.IGNORECASE),
    re.compile(r'(\d{4})[-/](\d{2})[-/](\d{2})'),
    re.compile(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})'),
]

_MONTH_MAP_UTIL = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
}
_MONTH_NAMES_OUT_UTIL = [
    '', 'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
]

_HIRE_ME_SIGNALS_RE = re.compile(
    r'\b(?:hire\s+me|looking\s+for\s+(?:work|a\s+job|employment|opportunity)|'
    r'available\s+for\s+(?:work|hire)|i\s+am\s+(?:a|an)\s+\w+\s+looking|'
    r'seeking\s+(?:work|employment|a\s+position|a\s+job)|'
    r'experienced\s+\w+\s+(?:available|seeking)|'
    r'my\s+(?:services|portfolio|cv|resume)|'
    r'contact\s+me\s+(?:for|if)|i\s+(?:have|possess)\s+\d+\s+years)\b',
    re.IGNORECASE,
)

_JOB_AD_SIGNALS_RE = re.compile(
    r'\b(?:we\s+(?:are|re)\s+(?:looking|hiring|seeking)|'
    r'our\s+(?:client|company|team|organisation)|'
    r'the\s+successful\s+candidate|minimum\s+requirements|'
    r'duties\s+(?:and|&)\s+responsibilities|salary\s+(?:range|package|offered)|'
    r'applications?\s+(?:are\s+)?invited|apply\s+(?:now|online|via|by|before)|'
    r'closing\s+date)\b',
    re.IGNORECASE,
)


def _is_skip_email_util(addr: str) -> bool:
    a = addr.lower()
    return any(frag in a for frag in _SKIP_EMAIL_FRAGMENTS)


def _first_email_util(text: str) -> str:
    for m in _EMAIL_RE_UTIL.finditer(text or ''):
        e = m.group(0)
        if not _is_skip_email_util(e):
            return e
    return ''


def extract_email_priority(how_to_apply: str = '', description: str = '', raw_text: str = '') -> str:
    """Priority: how_to_apply field → apply section in text → description → raw_text."""
    if how_to_apply:
        e = _first_email_util(how_to_apply)
        if e:
            return e
    for text in (description, raw_text):
        if not text:
            continue
        for m in _HOW_TO_APPLY_HEADERS_RE.finditer(text):
            snippet = text[m.start(): m.start() + 400]
            e = _first_email_util(snippet)
            if e:
                return e
    for text in (description, raw_text):
        e = _first_email_util(text)
        if e:
            return e
    return ''


def _normalise_date_util(match) -> str:
    g = match.groups()
    try:
        s = match.group(0)
        if re.match(r'\d{4}[-/]\d{2}[-/]\d{2}', s):
            year, month, day = int(g[0]), int(g[1]), int(g[2])
        elif re.match(r'\d{1,2}\s+[A-Za-z]', s):
            day = int(g[0])
            month = _MONTH_MAP_UTIL.get(g[1].lower()[:3], 0)
            year = int(g[2])
        elif re.match(r'[A-Za-z]', s):
            month = _MONTH_MAP_UTIL.get(g[0].lower()[:3], 0)
            day = int(g[1])
            year = int(g[2])
        else:
            day, month, year = int(g[0]), int(g[1]), int(g[2])
        if not (1 <= month <= 12 and 1 <= day <= 31 and 2020 <= year <= 2030):
            return ''
        return f'{day:02d} {_MONTH_NAMES_OUT_UTIL[month]} {year}'
    except Exception:
        return match.group(0).strip()[:40]


def extract_closing_date(text: str) -> str:
    """Extract closing/deadline date from job ad text."""
    if not text:
        return ''
    for hm in _CLOSING_HEADERS_RE.finditer(text):
        snippet = text[hm.end(): hm.end() + 80]
        for pat in _DATE_PATTERNS_UTIL:
            dm = pat.search(snippet)
            if dm:
                return _normalise_date_util(dm)
    for pat in _DATE_PATTERNS_UTIL:
        for dm in pat.finditer(text):
            raw = _normalise_date_util(dm)
            if raw:
                return raw
    return ''


def is_hire_me_post(title: str, description: str) -> bool:
    """Return True if this looks like a CV/hire-me ad, not a real vacancy."""
    text = (title + ' ' + description)
    hire_hits = len(_HIRE_ME_SIGNALS_RE.findall(text))
    ad_hits = len(_JOB_AD_SIGNALS_RE.findall(text))
    if _HIRE_ME_SIGNALS_RE.search(title):
        return True
    if hire_hits >= 2 and ad_hits == 0:
        return True
    if hire_hits >= 3 and ad_hits <= 1:
        return True
    return False
