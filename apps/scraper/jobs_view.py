from django.shortcuts import render
from django.core.paginator import Paginator
from apps.scraper.models import Job
from apps.mailer.models import Application

VALID_PAGE_SIZES = {25, 50, 100, 200}
DEFAULT_PAGE_SIZE = 50


def jobs_list(request):
    applied_ids = set(Application.objects.values_list("job_id", flat=True))

    try:
        page_size = int(request.GET.get("page_size", DEFAULT_PAGE_SIZE))
        if page_size not in VALID_PAGE_SIZES:
            page_size = DEFAULT_PAGE_SIZE
    except (ValueError, TypeError):
        page_size = DEFAULT_PAGE_SIZE

    jobs_qs = Job.objects.order_by("-match_score", "-scraped_at").only(
        "id", "title", "company", "platform", "match_score",
        "apply_email", "location", "scraped_at", "job_type", "salary"
    )

    paginator = Paginator(jobs_qs, page_size)
    page = request.GET.get("page", 1)
    jobs = paginator.get_page(page)  # get_page() clamps out-of-range values safely

    current = jobs.number
    total   = paginator.num_pages

    return render(request, "jobs.html", {
        "jobs":           jobs,
        "applied_ids":    applied_ids,
        "email_count":    Job.objects.exclude(apply_email="").count(),
        "no_email_count": Job.objects.filter(apply_email="").count(),
        "matched_count":  Job.objects.filter(match_score__gte=60).count(),
        "applied_count":  len(applied_ids),
        "total_jobs":     Job.objects.count(),
        "page_size":      page_size,
        "prev_page":      current - 1 if current > 1 else 1,
        "next_page":      current + 1 if current < total else total,
    })
