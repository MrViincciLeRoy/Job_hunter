from django.shortcuts import render, redirect
from django.contrib import messages
from .models import CV
from .parser import parse_cv


def upload_cv(request):
    if request.method == "POST" and request.FILES.get("cv"):
        cv = CV.objects.create(pdf=request.FILES["cv"])
        try:
            parsed = parse_cv(cv.pdf.path)
            cv.parsed_data = parsed
            cv.save()
            CV.objects.exclude(pk=cv.pk).update(active=False)
            messages.success(request, f"CV parsed for {parsed.get('name', 'Applicant')}.")
        except Exception as e:
            messages.error(request, f"Parse error: {e}")
        return redirect("dashboard")
    return render(request, "cv/upload.html")
