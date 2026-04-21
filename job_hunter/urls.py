from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from apps.scraper.views import dashboard, trigger_pipeline, cron_trigger, job_detail, spider_job, apply_single
from apps.cv.views import upload_cv

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", dashboard, name="dashboard"),
    path("upload-cv/", upload_cv, name="upload_cv"),
    path("trigger/", trigger_pipeline, name="trigger_pipeline"),
    path("cron/run/", cron_trigger, name="cron_trigger"),
    path("job/<int:job_id>/", job_detail, name="job_detail"),
    path("job/<int:job_id>/spider/", spider_job, name="spider_job"),
    path("job/<int:job_id>/apply/", apply_single, name="apply_single"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
