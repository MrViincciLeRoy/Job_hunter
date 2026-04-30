from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from apps.scraper.views import dashboard, trigger_pipeline, cron_trigger, job_detail, spider_job, apply_single, test_view
from apps.scraper.jobs_view import jobs_list
from apps.cv.views import upload_cv
from apps.cv.credentials_view import credentials_view, run_gmail_auth, oauth_callback

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", dashboard, name="dashboard"),
    path("jobs/", jobs_list, name="jobs_list"),
    path("upload-cv/", upload_cv, name="upload_cv"),
    path("credentials/", credentials_view, name="credentials"),
    path("credentials/gmail-auth/", run_gmail_auth, name="run_gmail_auth"),
    path("credentials/oauth-callback/", oauth_callback, name="oauth_callback"),
    path("trigger/", trigger_pipeline, name="trigger_pipeline"),
    path("cron/run/", cron_trigger, name="cron_trigger"),
    path("job/<int:job_id>/", job_detail, name="job_detail"),
    path("job/<int:job_id>/spider/", spider_job, name="spider_job"),
    path("job/<int:job_id>/apply/", apply_single, name="apply_single"),
    path("test/", test_view, name="test"),
    include(("apps.accounts.urls", "accounts"), namespace="accounts")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
