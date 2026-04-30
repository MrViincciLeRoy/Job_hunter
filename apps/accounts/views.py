import os
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

from .models import UserProfile, UserDocument, DOC_TYPES


def get_or_create_profile(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "accounts/login.html")


def logout_view(request):
    logout(request)
    return redirect("/accounts/login/")


@login_required
def onboarding_view(request):
    profile = get_or_create_profile(request.user)

    if profile.onboarding_done:
        return redirect("dashboard")

    if request.method == "POST":
        step = request.POST.get("step")

        if step == "personal":
            request.user.first_name = request.POST.get("first_name", "").strip()
            request.user.last_name  = request.POST.get("last_name", "").strip()
            request.user.save(update_fields=["first_name", "last_name"])
            profile.date_of_birth = request.POST.get("date_of_birth") or None
            profile.phone         = request.POST.get("phone", "").strip()
            profile.id_number     = request.POST.get("id_number", "").strip()
            profile.location      = request.POST.get("location", "").strip()
            profile.save()
            return JsonResponse({"ok": True})

        elif step == "professional":
            profile.occupation       = request.POST.get("occupation", "").strip()
            profile.years_experience = request.POST.get("years_experience", "").strip()
            profile.bio              = request.POST.get("bio", "").strip()
            profile.save()
            return JsonResponse({"ok": True})

        elif step == "online":
            profile.github_url    = request.POST.get("github_url", "").strip()
            profile.linkedin_url  = request.POST.get("linkedin_url", "").strip()
            profile.portfolio_url = request.POST.get("portfolio_url", "").strip()
            profile.save()
            return JsonResponse({"ok": True})

        elif step == "cv":
            f = request.FILES.get("file")
            if not f:
                return JsonResponse({"ok": False, "error": "No file selected"})
            data = f.read()
            doc = UserDocument.objects.create(
                user=request.user, doc_type="cv", label=f.name,
                file_data=data, file_name=f.name,
                mime_type=f.content_type or "application/octet-stream",
                file_size=len(data), is_primary=True,
            )
            _sync_cv_to_pipeline(request.user, data, f.name)
            return JsonResponse({"ok": True})

        elif step == "id":
            f = request.FILES.get("file")
            if not f:
                return JsonResponse({"ok": False, "error": "No file selected"})
            data = f.read()
            UserDocument.objects.create(
                user=request.user, doc_type="id_document", label=f.name,
                file_data=data, file_name=f.name,
                mime_type=f.content_type or "application/octet-stream",
                file_size=len(data),
            )
            return JsonResponse({"ok": True})

        elif step == "complete":
            profile.onboarding_done = True
            profile.save()
            return JsonResponse({"ok": True, "redirect": "/"})

    return render(request, "accounts/onboarding.html", {"profile": profile})


@login_required
def profile_view(request):
    profile = get_or_create_profile(request.user)

    if not profile.onboarding_done:
        return redirect("onboarding")

    if request.method == "POST":
        profile.phone         = request.POST.get("phone", "").strip()
        profile.location      = request.POST.get("location", "").strip()
        profile.bio           = request.POST.get("bio", "").strip()
        profile.github_url    = request.POST.get("github_url", "").strip()
        profile.portfolio_url = request.POST.get("portfolio_url", "").strip()
        profile.linkedin_url  = request.POST.get("linkedin_url", "").strip()
        profile.id_number     = request.POST.get("id_number", "").strip()
        profile.occupation    = request.POST.get("occupation", "").strip()
        profile.years_experience = request.POST.get("years_experience", "").strip()

        request.user.first_name = request.POST.get("first_name", "").strip()
        request.user.last_name  = request.POST.get("last_name", "").strip()
        request.user.save(update_fields=["first_name", "last_name"])

        photo_file = request.FILES.get("photo")
        if photo_file:
            profile.photo      = photo_file.read()
            profile.photo_mime = photo_file.content_type

        profile.save()
        messages.success(request, "Profile updated.")
        return redirect("accounts:profile")

    docs = UserDocument.objects.filter(user=request.user)
    doc_counts = {dt: docs.filter(doc_type=dt).count() for dt, _ in DOC_TYPES}

    return render(request, "accounts/profile.html", {
        "profile":    profile,
        "doc_counts": doc_counts,
        "doc_types":  DOC_TYPES,
        "docs":       docs,
    })


@login_required
def documents_view(request):
    if request.method == "POST":
        f        = request.FILES.get("file")
        doc_type = request.POST.get("doc_type", "other")
        label    = request.POST.get("label", "").strip() or (f.name if f else "Untitled")

        if not f:
            messages.error(request, "No file selected.")
            return redirect("accounts:documents")

        data = f.read()
        doc = UserDocument.objects.create(
            user=request.user, doc_type=doc_type, label=label,
            file_data=data, file_name=f.name,
            mime_type=f.content_type or "application/octet-stream",
            file_size=len(data),
        )

        if doc_type == "cv":
            if not UserDocument.objects.filter(user=request.user, doc_type="cv", is_primary=True).exclude(pk=doc.pk).exists():
                doc.is_primary = True
                doc.save(update_fields=["is_primary"])
            _sync_cv_to_pipeline(request.user, data, f.name)

        messages.success(request, f"'{label}' uploaded.")
        return redirect("accounts:documents")

    docs = UserDocument.objects.filter(user=request.user)
    grouped = {}
    for dt, dt_label in DOC_TYPES:
        grouped[dt] = {"label": dt_label, "docs": docs.filter(doc_type=dt)}

    return render(request, "accounts/documents.html", {
        "grouped":   grouped,
        "doc_types": DOC_TYPES,
        "total":     docs.count(),
    })


@login_required
def document_download(request, doc_id):
    doc = get_object_or_404(UserDocument, pk=doc_id, user=request.user)
    resp = HttpResponse(bytes(doc.file_data), content_type=doc.mime_type or "application/octet-stream")
    resp["Content-Disposition"] = f'attachment; filename="{doc.file_name}"'
    return resp


@login_required
@require_POST
def document_delete(request, doc_id):
    doc = get_object_or_404(UserDocument, pk=doc_id, user=request.user)
    doc.delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def document_set_primary(request, doc_id):
    doc = get_object_or_404(UserDocument, pk=doc_id, user=request.user, doc_type="cv")
    UserDocument.objects.filter(user=request.user, doc_type="cv").update(is_primary=False)
    doc.is_primary = True
    doc.save(update_fields=["is_primary"])
    _sync_cv_to_pipeline(request.user, bytes(doc.file_data), doc.file_name)
    return JsonResponse({"ok": True})


@login_required
def photo_view(request):
    profile = get_or_create_profile(request.user)
    if not profile.photo:
        return HttpResponse(status=404)
    return HttpResponse(bytes(profile.photo), content_type=profile.photo_mime or "image/jpeg")


def _sync_cv_to_pipeline(user, pdf_bytes, filename):
    try:
        from apps.cv.models import CV
        from apps.cv.parser import parse_cv_bytes
        CV.objects.filter(user=user).update(active=False)
        cv = CV(pdf_filename=filename, user=user)
        cv.pdf_data = pdf_bytes
        cv.save()
        try:
            parsed = parse_cv_bytes(pdf_bytes)
            cv.parsed_data = parsed
            cv.active = True
            cv.save()
        except Exception as e:
            print(f"[accounts] CV parse error: {e}")
            cv.active = True
            cv.save()
    except Exception as e:
        print(f"[accounts] CV sync error: {e}")