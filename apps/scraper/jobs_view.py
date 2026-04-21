from django.shortcuts import render
from apps.scraper.models import Job
from apps.mailer.models import Application


def jobs_list(request):
    jobs = Job.objects.order_by("-apply_email", "-match_score", "-scraped_at").select_related()

    # Annotate applied status
    applied_ids = set(Application.objects.values_list("job_id", flat=True))

    email_count = Job.objects.exclude(apply_email="").count()
    no_email_count = Job.objects.filter(apply_email="").count()
    matched_count = Job.objects.filter(match_score__gte=60).count()
    applied_count = len(applied_ids)
    total_jobs = Job.objects.count()

    return render(request, "jobs.html", {
        "jobs": jobs,
        "email_count": email_count,
        "no_email_count": no_email_count,
        "matched_count": matched_count,
        "applied_count": applied_count,
        "total_jobs": total_jobs,
    })
