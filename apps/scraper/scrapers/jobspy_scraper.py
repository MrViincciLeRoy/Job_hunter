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
            "title":       str(row.get("title", "") or ""),
            "company":     str(row.get("company", "") or ""),
            "location":    str(row.get("location", "") or ""),
            "description": str(row.get("description", "") or ""),
            "url":         str(row.get("job_url", "") or ""),
            "apply_email": str(email) if pd.notna(email) and email else "",
            "salary":      str(row.get("min_amount", "") or ""),
            "job_type":    str(row.get("job_type", "") or ""),
            "platform":    platform,
        })
    return jobs


def scrape_linkedin(keywords: str, limit: int = 20) -> list:
    if not JOBSPY_AVAILABLE or not keywords:
        return []
    try:
        df = scrape_jobs(
            site_name=["linkedin"],
            search_term=keywords,
            location="South Africa",
            results_wanted=min(limit, 50),
        )
        jobs = _df_to_list(df, "linkedin")
        print(f"[LinkedIn] {len(jobs)} jobs scraped")
        return jobs
    except Exception as e:
        print(f"[LinkedIn] Error: {e}")
        return []


def scrape_indeed(keywords: str, limit: int = 20) -> list:
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
        print(f"[Indeed] {len(jobs)} jobs scraped")
        return jobs
    except Exception as e:
        print(f"[Indeed] Error: {e}")
        return []
