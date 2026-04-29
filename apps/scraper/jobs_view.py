from django.shortcuts import render
from django.core.paginator import Paginator
from django.db.models import Q
from apps.scraper.models import Job
from apps.mailer.models import Application

VALID_PAGE_SIZES = {25, 50, 100, 200}
DEFAULT_PAGE_SIZE = 50
GOV_PLATFORMS = {"dpsa", "sayouth", "essa", "govza"}

# Maps dropdown value → DB job_type icontains patterns
JOB_TYPE_MAP = {
    "internship": ["internship"],
    "learnership": ["learnership"],
    "bursary": ["bursary", "scholarship"],
    "graduate": ["graduate"],
    "entry level": ["entry level", "entry-level"],
    "permanent": ["permanent"],
    "contract": ["contract"],
    "temporary": ["temporary"],
    "part-time": ["part-time", "part time"],
    "full-time": ["full-time", "full time"],
    "government": ["government"],
    "government / permanent": ["government / permanent"],
}


def jobs_list(request):
    applied_ids = set(Application.objects.values_list("job_id", flat=True))

    # ── query params ──────────────────────────────────────────────────────
    try:
        page_size = int(request.GET.get("page_size", DEFAULT_PAGE_SIZE))
        if page_size not in VALID_PAGE_SIZES:
            page_size = DEFAULT_PAGE_SIZE
    except (ValueError, TypeError):
        page_size = DEFAULT_PAGE_SIZE

    tab = request.GET.get("tab", "email")
    platforms = request.GET.getlist("platform")  # multi-value
    job_type = request.GET.get("job_type", "").strip().lower()
    search = request.GET.get("q", "").strip()

    # ── base queryset ─────────────────────────────────────────────────────
    qs = Job.objects.order_by("-match_score", "-scraped_at").only(
        "id", "title", "company", "platform", "match_score",
        "apply_email", "location", "scraped_at", "job_type", "salary"
    )

    # ── tab filter ────────────────────────────────────────────────────────
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

    # ── platform filter ───────────────────────────────────────────────────
    valid_platforms = [p for p in platforms if p and p != "all"]
    if valid_platforms:
        qs = qs.filter(platform__in=valid_platforms)

    # ── job type filter ───────────────────────────────────────────────────
    if job_type and job_type in JOB_TYPE_MAP:
        patterns = JOB_TYPE_MAP[job_type]
        q_obj = Q()
        for p in patterns:
            q_obj |= Q(job_type__icontains=p)
        qs = qs.filter(q_obj)

    # ── search ────────────────────────────────────────────────────────────
    if search:
        qs = qs.filter(
            Q(title__icontains=search) |
            Q(company__icontains=search) |
            Q(platform__icontains=search)
        )

    # ── paginate ──────────────────────────────────────────────────────────
    paginator = Paginator(qs, page_size)
    jobs = paginator.get_page(request.GET.get("page", 1))
    current = jobs.number
    total = paginator.num_pages

    # counts for the tab bar (always against full DB, unfiltered by tab)
    total_qs = Job.objects
    
    return render(request, "jobs.html", {
        "jobs": jobs,
        "applied_ids": applied_ids,
        "email_count": total_qs.exclude(apply_email="").count(),
        "no_email_count": total_qs.filter(apply_email="").count(),
        "matched_count": total_qs.filter(match_score__gte=60).count(),
        "applied_count": len(applied_ids),
        "total_jobs": total_qs.count(),
        "page_size": page_size,
        "prev_page": current - 1 if current > 1 else 1,
        "next_page": current + 1 if current < total else total,
        # pass active filters back so template can reflect state
        "active_tab": tab,
        "active_platforms": valid_platforms,
        "active_job_type": job_type,
        "active_search": search,
        "filter_count": qs.count(),
    })
