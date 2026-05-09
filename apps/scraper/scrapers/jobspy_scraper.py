import pandas as pd

try:
    from jobspy import scrape_jobs
    JOBSPY_AVAILABLE = True
except ImportError:
    JOBSPY_AVAILABLE = False


def _val(row, *keys):
    for k in keys:
        v = row.get(k)
        if v is not None and not (isinstance(v, float) and pd.isna(v)):
            return str(v).strip()
    return ""


def _salary(row):
    mn = _val(row, "min_amount")
    mx = _val(row, "max_amount")
    cur = _val(row, "currency") or "ZAR"
    interval = _val(row, "interval")
    if mn and mx:
        return f"{cur} {mn} – {mx}{' / ' + interval if interval else ''}"
    if mn:
        return f"{cur} {mn}{' / ' + interval if interval else ''}"
    return ""


def _job_type(row):
    jt = _val(row, "job_type")
    if jt and jt.lower() not in ("none", "nan", ""):
        return jt
    jl = _val(row, "job_level")
    if jl and jl.lower() not in ("none", "nan", ""):
        return jl
    return ""


def _description(row, platform):
    desc = _val(row, "description")
    if desc and desc.lower() not in ("none", "nan"):
        return desc[:3000]

    parts = []
    for label, key in [
        ("Function", "job_function"),
        ("Industry", "company_industry"),
        ("Skills", "skills"),
        ("Experience", "experience_range"),
        ("Work type", "work_from_home_type"),
    ]:
        v = _val(row, key)
        if v and v not in ("None", "nan"):
            parts.append(f"{label}: {v}")

    if row.get("is_remote") is True:
        parts.append("Remote: Yes")

    company_desc = _val(row, "company_description")
    if company_desc and company_desc not in ("None", "nan"):
        parts.append(f"\nAbout the company:\n{company_desc[:500]}")

    if parts:
        return "\n".join(parts)

    return f"No description available from {platform} — visit the posting link for full details."


def _df_to_list(df: pd.DataFrame, platform: str) -> list:
    jobs = []
    for _, row in df.iterrows():
        row = row.to_dict()
        title = _val(row, "title")
        if not title:
            continue

        date_posted = row.get("date_posted")
        closing_date = str(date_posted) if date_posted and str(date_posted) not in ("None", "nan", "") else ""

        jobs.append({
            "title":        title,
            "company":      _val(row, "company"),
            "location":     _val(row, "location"),
            "description":  _description(row, platform),
            "url":          _val(row, "job_url"),
            "apply_email":  _val(row, "emails"),
            "salary":       _salary(row),
            "job_type":     _job_type(row),
            "closing_date": closing_date,
            "platform":     platform,
        })
    return jobs


def scrape_indeed(keywords: str, limit: int = 50) -> list:
    if not JOBSPY_AVAILABLE or not keywords:
        return []
    try:
        df = scrape_jobs(
            site_name=["indeed"],
            search_term=keywords,
            location="South Africa",
            results_wanted=min(limit, 50),
            country_indeed="south africa",
        )
        jobs = _df_to_list(df, "indeed")
        print(f"[Indeed] {len(jobs)} jobs")
        return jobs
    except Exception as e:
        print(f"[Indeed] Error: {e}")
        return []


def scrape_google(keywords: str, limit: int = 50) -> list:
    if not JOBSPY_AVAILABLE or not keywords:
        return []
    try:
        df = scrape_jobs(
            site_name=["google"],
            google_search_term=f"{keywords} jobs South Africa",
            location="South Africa",
            results_wanted=min(limit, 50),
        )
        jobs = _df_to_list(df, "google")
        print(f"[Google Jobs] {len(jobs)} jobs")
        return jobs
    except Exception as e:
        print(f"[Google Jobs] Error: {e}")
        return []
