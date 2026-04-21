import pandas as pd

try:
    from jobspy import scrape_jobs
    JOBSPY_AVAILABLE = True
except ImportError:
    JOBSPY_AVAILABLE = False


def _df_to_list(df: pd.DataFrame, platform: str) -> list:
    jobs = []
    for _, row in df.iterrows():
        email = row.get("emails", "")
        jobs.append({
            "title": str(row.get("title", "")),
            "company": str(row.get("company", "")),
            "location": str(row.get("location", "")),
            "description": str(row.get("description", "") or ""),
            "url": str(row.get("job_url", "")),
            "apply_email": str(email) if pd.notna(email) and email else "",
            "platform": platform,
        })
    return jobs


def scrape_linkedin(keywords: str, limit: int = 20) -> list:
    if not JOBSPY_AVAILABLE:
        return []
    df = scrape_jobs(
        site_name=["linkedin"],
        search_term=keywords,
        location="South Africa",
        results_wanted=limit,
    )
    return _df_to_list(df, "linkedin")


def scrape_indeed(keywords: str, limit: int = 20) -> list:
    if not JOBSPY_AVAILABLE:
        return []
    df = scrape_jobs(
        site_name=["indeed"],
        search_term=keywords,
        location="South Africa",
        results_wanted=limit,
        country_indeed="south africa",
    )
    return _df_to_list(df, "indeed")
