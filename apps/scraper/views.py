from django.shortcuts import render, redirect, get_object_or_404
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
        "cv": cv, "jobs": jobs, "applications": applications,
        "total_jobs": jobs.count(), "applied_count": applications.count(),
        "matched_count": jobs.filter(match_score__gte=60).count(),
        "top_jobs": jobs.filter(match_score__gte=60).exclude(apply_email="")[:5],
    })


def job_detail(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    app = getattr(job, "application", None)
    return JsonResponse({
        "id": job.pk, "title": job.title, "company": job.company,
        "location": job.location, "platform": job.platform, "url": job.url,
        "apply_email": job.apply_email, "match_score": job.match_score,
        "description": job.description,
        "scraped_at": job.scraped_at.strftime("%d %b %Y · %H:%M"),
        "applied": app is not None,
        "applied_at": app.sent_at.strftime("%d %b %Y · %H:%M") if app else None,
        "cover_letter": app.cover_letter if app else None,
        "status": app.status if app else None,
    })


@require_POST
def spider_job(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    if not job.url:
        return JsonResponse({"error": "No URL for this job"}, status=400)

    from apps.scraper.scrapers.spider import spider_url
    result = spider_url(job.url)

    if result["error"]:
        return JsonResponse({"error": result["error"]}, status=422)

    updated = False
    if result["emails"] and not job.apply_email:
        job.apply_email = result["emails"][0]
        updated = True
    if result["description"] and len(result["description"]) > len(job.description):
        job.description = result["description"]
        updated = True
    if updated:
        job.save()

    if not job.apply_email:
        job.delete()
        return JsonResponse({"no_email": True, "deleted": True, "all_emails": []})

    app = getattr(job, "application", None)
    return JsonResponse({
        "id": job.pk, "apply_email": job.apply_email,
        "all_emails": result["emails"], "phone": result["phone"],
        "followed_url": result["followed_url"],
        "description_updated": bool(result["description"]),
        "applied": app is not None, "deleted": False,
    })


@require_POST
def apply_single(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    cv = CV.objects.filter(active=True).last()

    if not cv:
        return JsonResponse({"error": "No active CV"}, status=400)
    if not job.apply_email:
        return JsonResponse({"error": "No email address for this job"}, status=400)
    if hasattr(job, "application"):
        return JsonResponse({"error": "Already applied"}, status=400)

    pdf_bytes = cv.get_pdf_bytes()
    if not pdf_bytes:
        return JsonResponse({"error": "CV file missing — please re-upload at /upload-cv/"}, status=400)

    try:
        from apps.mailer.sender import send_application
        ok, result = send_application(
            cv.parsed_data,
            {
                "title": job.title,
                "company": job.company,
                "description": job.description,
                "apply_email": job.apply_email,
            },
            pdf_bytes,
            cv.pdf_filename or "CV.pdf",
        )
        if ok:
            Application.objects.create(job=job, status="sent", cover_letter=result)
            return JsonResponse({"success": True, "cover_letter": result})
        return JsonResponse({"error": result}, status=500)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


def _spider_and_filter(jobs_qs, spider_fn):
    to_delete = []
    for job in jobs_qs:
        try:
            result = spider_fn(job.url)
            if result["emails"]:
                job.apply_email = result["emails"][0]
                updates = ["apply_email"]
                if result["description"] and len(result["description"]) > len(job.description):
                    job.description = result["description"]
                    updates.append("description")
                job.save(update_fields=updates)
            else:
                to_delete.append(job.pk)
        except Exception:
            to_delete.append(job.pk)
    if to_delete:
        Job.objects.filter(pk__in=to_delete).delete()


def _run_pipeline(steps, threshold=60, dry_run=False):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "job_hunter.settings")

    from apps.scraper.scrapers.jobspy_scraper import scrape_linkedin, scrape_indeed
    from apps.scraper.scrapers.pnet import scrape_pnet
    from apps.scraper.scrapers.careerjunction import scrape_careerjunction
    from apps.scraper.scrapers.spider import spider_url
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
                if not j.get("title"):
                    continue
                Job.objects.get_or_create(
                    title=j["title"], company=j.get("company", ""), platform=j["platform"],
                    defaults={"location": j.get("location", ""), "description": j.get("description", ""),
                              "url": j.get("url", ""), "apply_email": j.get("apply_email", "")},
                )

    if "spider" in steps:
        no_email = list(Job.objects.filter(apply_email="").exclude(url="")[:60])
        _spider_and_filter(no_email, spider_url)

    if "match" in steps:
        cv = CV.objects.filter(active=True).last()
        if cv:
            for job in Job.objects.filter(match_score=0).exclude(apply_email=""):
                try:
                    score = match_job_to_cv(cv.parsed_data, {"title": job.title, "description": job.description})
                    job.match_score = score
                    job.save(update_fields=["match_score"])
                except Exception:
                    pass

    if "apply" in steps:
        cv = CV.objects.filter(active=True).last()
        if cv:
            pdf_bytes = cv.get_pdf_bytes()
            if not pdf_bytes:
                return
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
                        pdf_bytes, cv.pdf_filename or "CV.pdf",
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
        "all": ["scrape", "spider", "match", "apply"],
        "scrape": ["scrape"], "spider": ["spider"],
        "match": ["match"], "apply": ["apply"],
    }
    steps = steps_map.get(action, ["scrape", "spider", "match", "apply"])
    thread = threading.Thread(target=_run_pipeline, args=(steps,), kwargs={"dry_run": dry_run}, daemon=True)
    thread.start()
    label = {"all": "Full pipeline", "scrape": "Scrape", "spider": "Spider",
             "match": "Match", "apply": "Apply"}.get(action, action)
    messages.success(request, f"⚡ {label} started in background. Refresh in ~60s to see results.")
    return redirect("dashboard")

# ── Add this view to apps/scraper/views.py ───────────────────────────────────
# Also add to job_hunter/urls.py:
#   from apps.scraper.views import cron_cleanup
#   path("cron/cleanup/", cron_cleanup, name="cron_cleanup"),

@csrf_exempt
def cron_cleanup(request):
    """
    Called by the GitHub Actions cleanup workflow.
    POST body params:
      dry_run  : "yes" | "no"   (default: "yes" — safe by default)
      platform : optional slug  (e.g. "pnet")
    """
    secret = request.headers.get("X-Cron-Secret", "")
    if secret != os.getenv("CRON_SECRET", ""):
        return JsonResponse({"error": "unauthorized"}, status=401)

    dry_run  = request.POST.get("dry_run", "yes") != "no"
    platform = request.POST.get("platform", "").strip() or None

    applied_job_ids = set(Application.objects.values_list("job_id", flat=True))
    qs = Job.objects.exclude(pk__in=applied_job_ids)
    if platform:
        qs = qs.filter(platform__iexact=platform)

    count = qs.count()

    if dry_run:
        return JsonResponse({
            "status":    "dry_run",
            "would_delete": count,
            "applied_kept": Job.objects.filter(pk__in=applied_job_ids).count(),
            "platform_filter": platform,
        })

    deleted, _ = qs.delete()
    return JsonResponse({
        "status":  "deleted",
        "deleted": deleted,
        "applied_kept": Job.objects.filter(pk__in=applied_job_ids).count(),
        "platform_filter": platform,
    })

@csrf_exempt
def cron_trigger(request):
    secret = request.headers.get("X-Cron-Secret", "")
    if secret != os.getenv("CRON_SECRET", ""):
        return JsonResponse({"error": "unauthorized"}, status=401)
    thread = threading.Thread(target=_run_pipeline, args=(["scrape", "spider", "match", "apply"],), daemon=True)
    thread.start()
    return JsonResponse({"status": "pipeline started"})
