from django.shortcuts import render
from django.core.paginator import Paginator
from apps.scraper.models import Job
from apps.mailer.models import Application


def jobs_list(request):
    applied_ids = set(Application.objects.values_list("job_id", flat=True))

    jobs_qs = Job.objects.order_by("-match_score", "-scraped_at").only(
        "id", "title", "company", "platform", "match_score",
        "apply_email", "location", "scraped_at", "job_type", "salary"
    )

    paginator = Paginator(jobs_qs, 50)
    page = request.GET.get("page", 1)
    jobs = paginator.get_page(page)

    return render(request, "jobs.html", {
        "jobs": jobs,
        "applied_ids": applied_ids,
        "email_count": Job.objects.exclude(apply_email="").count(),
        "no_email_count": Job.objects.filter(apply_email="").count(),
        "matched_count": Job.objects.filter(match_score__gte=60).count(),
        "applied_count": len(applied_ids),
        "total_jobs": Job.objects.count(),
        "page_obj": jobs,
    })
