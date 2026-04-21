from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
import threading
import os

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


def _run_pipeline(steps, threshold=60, dry_run=False):
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "job_hunter.settings")

    from apps.scraper.scrapers.jobspy_scraper import scrape_linkedin, scrape_indeed
    from apps.scraper.scrapers.pnet import scrape_pnet
    from apps.scraper.scrapers.careerjunction import scrape_careerjunction
    from apps.matcher.matcher import match_job_to_cv
    from apps.mailer.sender import send_application

    if "scrape" in steps:
        cv = CV.objects.filter(active=True).last()
        if cv:
            skills = cv.parsed_data.get("skills", [])
            keywords = " ".join(skills[:3]) if skills else "developer"
            all_jobs = []
            for fn in [scrape_linkedin, scrape_indeed, scrape_pnet, scrape_careerjunction]:
                try:
                    all_jobs += fn(keywords, limit=20)
                except Exception:
                    pass
            for j in all_jobs:
                if j.get("title"):
                    Job.objects.get_or_create(
                        title=j["title"], company=j.get("company", ""), platform=j["platform"],
                        defaults={"location": j.get("location", ""), "description": j.get("description", ""),
                                  "url": j.get("url", ""), "apply_email": j.get("apply_email", "")},
                    )

    if "match" in steps:
        cv = CV.objects.filter(active=True).last()
        if cv:
            for job in Job.objects.filter(match_score=0):
                try:
                    score = match_job_to_cv(cv.parsed_data, {"title": job.title, "description": job.description})
                    job.match_score = score
                    job.save(update_fields=["match_score"])
                except Exception:
                    pass

    if "apply" in steps:
        cv = CV.objects.filter(active=True).last()
        if cv:
            jobs = (Job.objects.filter(match_score__gte=threshold)
                    .exclude(apply_email="").exclude(application__isnull=False))
            for job in jobs:
                if dry_run:
                    continue
                try:
                    ok, result = send_application(
                        cv.parsed_data,
                        {"title": job.title, "company": job.company,
                         "description": job.description, "apply_email": job.apply_email},
                        cv.pdf.path,
                    )
                    if ok:
                        Application.objects.create(job=job, status="sent", cover_letter=result)
                except Exception:
                    pass


@require_POST
def trigger_pipeline(request):
    action = request.POST.get("action", "all")
    dry_run = request.POST.get("dry_run") == "1"

    steps_map = {
        "all": ["scrape", "match", "apply"],
        "scrape": ["scrape"],
        "match": ["match"],
        "apply": ["apply"],
    }
    steps = steps_map.get(action, ["scrape", "match", "apply"])

    thread = threading.Thread(target=_run_pipeline, args=(steps,), kwargs={"dry_run": dry_run}, daemon=True)
    thread.start()

    label = {"all": "Full pipeline", "scrape": "Scrape", "match": "Match", "apply": "Apply"}.get(action, action)
    messages.success(request, f"⚡ {label} started in background. Refresh in ~60s to see results.")
    return redirect("dashboard")


@csrf_exempt
def cron_trigger(request):
    secret = request.headers.get("X-Cron-Secret", "")
    if secret != os.getenv("CRON_SECRET", ""):
        return JsonResponse({"error": "unauthorized"}, status=401)

    thread = threading.Thread(target=_run_pipeline, args=(["scrape", "match", "apply"],), daemon=True)
    thread.start()
    return JsonResponse({"status": "pipeline started"})
