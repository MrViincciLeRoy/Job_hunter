from django.shortcuts import render
from apps.scraper.models import Job
from apps.cv.models import CV
from apps.mailer.models import Application


def dashboard(request):
    cv = CV.objects.filter(active=True).last()
    jobs = Job.objects.order_by("-match_score", "-scraped_at")
    applications = Application.objects.select_related("job").order_by("-sent_at")

    return render(request, "dashboard.html", {
        "cv": cv,
        "jobs": jobs,
        "applications": applications,
        "total_jobs": jobs.count(),
        "applied_count": applications.count(),
        "matched_count": jobs.filter(match_score__gte=60).count(),
        "top_jobs": jobs.filter(match_score__gte=60).exclude(apply_email="")[:5],
    })
