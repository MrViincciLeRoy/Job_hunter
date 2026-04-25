from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
import threading
import requests as http_requests
import os

from apps.scraper.models import Job
from apps.cv.models import CV
from apps.mailer.models import Application

GITHUB_REPO = os.getenv("GITHUB_REPO", "")        # e.g. yourname/job-hunter
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_WORKFLOW = "scrape.yml"


def _trigger_github_workflow(step="all"):
    if not GITHUB_REPO or not GITHUB_TOKEN:
        return False, "GITHUB_REPO or GITHUB_TOKEN not set in environment."
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{GITHUB_WORKFLOW}/dispatches"
    resp = http_requests.post(
        url,
        json={"ref": "main", "inputs": {"step": step}},
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
        timeout=10,
    )
    if resp.status_code == 204:
        return True, None
    return False, f"GitHub API returned {resp.status_code}: {resp.text[:200]}"


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


def _run_apply(threshold=60, dry_run=False):
    from apps.mailer.sender import send_application
    cv = CV.objects.filter(active=True).last()
    if not cv:
        return
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

    # Apply runs locally on Render (fast — just sending emails)
    if action == "apply":
        thread = threading.Thread(target=_run_apply, kwargs={"dry_run": dry_run}, daemon=True)
        thread.start()
        messages.success(request, "✉ Apply started — sending emails now.")
        return redirect("dashboard")

    # Scrape / spider / match / all → delegate to GitHub Actions
    step = action if action in ("scrape", "spider", "match") else "all"
    ok, error = _trigger_github_workflow(step)

    label = {"all": "Scrape + Spider + Match", "scrape": "Scrape",
             "spider": "Spider", "match": "Match"}.get(step, step)

    if ok:
        messages.success(request, f"⚡ {label} triggered on GitHub Actions — results will appear in ~5 min.")
    else:
        messages.error(request, f"GitHub dispatch failed: {error}")

    return redirect("dashboard")


@csrf_exempt
def cron_cleanup(request):
    secret = request.headers.get("X-Cron-Secret", "")
    if secret != os.getenv("CRON_SECRET", ""):
        return JsonResponse({"error": "unauthorized"}, status=401)

    dry_run = request.POST.get("dry_run", "yes") != "no"
    platform = request.POST.get("platform", "").strip() or None

    applied_job_ids = set(Application.objects.values_list("job_id", flat=True))
    qs = Job.objects.exclude(pk__in=applied_job_ids)
    if platform:
        qs = qs.filter(platform__iexact=platform)

    count = qs.count()

    if dry_run:
        return JsonResponse({
            "status": "dry_run",
            "would_delete": count,
            "applied_kept": Job.objects.filter(pk__in=applied_job_ids).count(),
            "platform_filter": platform,
        })

    deleted, _ = qs.delete()
    return JsonResponse({
        "status": "deleted",
        "deleted": deleted,
        "applied_kept": Job.objects.filter(pk__in=applied_job_ids).count(),
        "platform_filter": platform,
    })


@csrf_exempt
def cron_trigger(request):
    secret = request.headers.get("X-Cron-Secret", "")
    if secret != os.getenv("CRON_SECRET", ""):
        return JsonResponse({"error": "unauthorized"}, status=401)
    ok, error = _trigger_github_workflow("all")
    if ok:
        return JsonResponse({"status": "github workflow triggered"})
    return JsonResponse({"status": "error", "detail": error}, status=500)
