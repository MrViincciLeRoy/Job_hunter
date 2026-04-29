from django.shortcuts import render
from django.core.paginator import Paginator
from django.db.models import Q
from apps.scraper.models import Job
from apps.mailer.models import Application

VALID_PAGE_SIZES = {25, 50, 100, 200}
DEFAULT_PAGE_SIZE = 50
GOV_PLATFORMS = {"dpsa", "sayouth", "essa", "govza"}

# Maps UI job_type slug → job_type strings stored on Job records.
# Uses icontains so partial matches work (e.g. "Government / Permanent" contains "permanent").
JOB_TYPE_MAP = {
    "internship":             ["internship"],
    "learnership":            ["learnership"],
    "bursary":                ["bursary", "scholarship"],
    "graduate":               ["graduate"],
    "entry level":            ["entry level", "entry-level"],
    "permanent":              ["permanent"],
    "contract":               ["contract"],
    "temporary":              ["temporary"],
    "part-time":              ["part-time", "part time"],
    "full-time":              ["full-time", "full time"],
    "government":             ["government"],
    "government / permanent": ["government / permanent"],
}

PLATFORM_DEFS = [
    ("linkedin",          "LinkedIn",         False),
    ("indeed",            "Indeed",           False),
    ("pnet",              "PNet",             False),
    ("careerjunction",    "CareerJunction",   False),
    ("careerjunction_it", "CareerJunction IT",False),
    ("careers24",         "Careers24",        False),
    ("jobmail",           "JobMail",          False),
    ("gumtree",           "Gumtree",          False),
    ("dpsa",              "DPSA",             True),
    ("sayouth",           "SAYouth",          True),
    ("essa",              "ESSA",             True),
    ("govza",             "Gov.za",           True),
]

# Job types that are only meaningful for government platforms.
# When ONLY gov platforms are selected, hide commercial-only types in the UI.
GOV_JOB_TYPES = {
    "internship", "learnership", "bursary", "graduate",
    "entry level", "government", "government / permanent",
}

# Job types that never appear on DPSA/gov platforms.
# These are always 0 when filtering gov-only and should be shown as N/A.
COMMERCIAL_ONLY_TYPES = {"contract", "temporary", "part-time", "full-time"}


def jobs_list(request):
    applied_ids = set(Application.objects.values_list("job_id", flat=True))

    try:
        page_size = int(request.GET.get("page_size", DEFAULT_PAGE_SIZE))
        if page_size not in VALID_PAGE_SIZES:
            page_size = DEFAULT_PAGE_SIZE
    except (ValueError, TypeError):
        page_size = DEFAULT_PAGE_SIZE

    tab = request.GET.get("tab", "email")
    platforms = request.GET.getlist("platform")
    job_type = request.GET.get("job_type", "").strip().lower()
    search = request.GET.get("q", "").strip()

    qs = Job.objects.order_by("-match_score", "-scraped_at").only(
        "id", "title", "company", "platform", "match_score",
        "apply_email", "location", "scraped_at", "job_type", "salary"
    )

    if tab == "email":
        qs = qs.filter(~Q(apply_email=""))
    elif tab == "matched":
        qs = qs.filter(match_score__gte=60)
    elif tab == "applied":
        qs = qs.filter(pk__in=applied_ids)
    elif tab == "gov":
        qs = qs.filter(platform__in=GOV_PLATFORMS, match_score__gte=50)
    elif tab == "noemail":
        qs = qs.filter(apply_email="")

    valid_platforms = [p for p in platforms if p and p != "all"]
    if valid_platforms:
        qs = qs.filter(platform__in=valid_platforms)

    # Determine if only gov platforms are selected (for UI hint)
    only_gov_selected = bool(valid_platforms) and all(p in GOV_PLATFORMS for p in valid_platforms)

    # Apply job type filter — skip obviously inapplicable combinations
    # (e.g. DPSA + full-time will always be 0, no need to query)
    type_filter_active = bool(job_type and job_type in JOB_TYPE_MAP)
    type_is_commercial_only = job_type in COMMERCIAL_ONLY_TYPES
    type_impossible = only_gov_selected and type_is_commercial_only

    if type_filter_active and not type_impossible:
        patterns = JOB_TYPE_MAP[job_type]
        q_obj = Q()
        for p in patterns:
            q_obj |= Q(job_type__icontains=p)
        qs = qs.filter(q_obj)
    elif type_filter_active and type_impossible:
        # Filter will always return 0 — apply it anyway so the count is correct
        # but we'll pass a hint to the template
        patterns = JOB_TYPE_MAP[job_type]
        q_obj = Q()
        for p in patterns:
            q_obj |= Q(job_type__icontains=p)
        qs = qs.filter(q_obj)

    if search:
        qs = qs.filter(
            Q(title__icontains=search) |
            Q(company__icontains=search) |
            Q(platform__icontains=search)
        )

    paginator = Paginator(qs, page_size)
    jobs = paginator.get_page(request.GET.get("page", 1))
    current = jobs.number
    total = paginator.num_pages

    total_qs = Job.objects
    email_count    = total_qs.exclude(apply_email="").count()
    matched_count  = total_qs.filter(match_score__gte=60).count()
    applied_count  = len(applied_ids)
    no_email_count = total_qs.filter(apply_email="").count()
    gov_count      = total_qs.filter(platform__in=GOV_PLATFORMS, match_score__gte=50).count()

    tab_defs = [
        ("email",   "✉ Has Email",  "act-green"  if tab == "email"   else "", email_count),
        ("matched", "★ Matched",    "act-purple" if tab == "matched" else "", matched_count),
        ("applied", "✓ Applied",    "act-orange" if tab == "applied" else "", applied_count),
        ("gov",     "🏛 Gov",       "act-gov"    if tab == "gov"     else "", gov_count),
        ("noemail", "✗ No Email",   "act-green"  if tab == "noemail" else "", no_email_count),
        ("all",     "All",          "act-green"  if tab == "all"     else "", None),
    ]

    return render(request, "jobs.html", {
        "jobs":               jobs,
        "applied_ids":        applied_ids,
        "email_count":        email_count,
        "no_email_count":     no_email_count,
        "matched_count":      matched_count,
        "applied_count":      applied_count,
        "total_jobs":         total_qs.count(),
        "page_size":          page_size,
        "prev_page":          current - 1 if current > 1 else 1,
        "next_page":          current + 1 if current < total else total,
        "active_tab":         tab,
        "active_platforms":   valid_platforms,
        "active_job_type":    job_type,
        "active_search":      search,
        "filter_count":       qs.count(),
        "tab_defs":           tab_defs,
        "platform_defs":      PLATFORM_DEFS,
        "only_gov_selected":  only_gov_selected,
        "type_impossible":    type_impossible,
        "gov_job_types":      GOV_JOB_TYPES,
        "commercial_only_types": COMMERCIAL_ONLY_TYPES,
    })
