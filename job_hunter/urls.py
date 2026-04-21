from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from apps.scraper.views import dashboard, trigger_pipeline, cron_trigger, job_detail
from apps.cv.views import upload_cv

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", dashboard, name="dashboard"),
    path("upload-cv/", upload_cv, name="upload_cv"),
    path("trigger/", trigger_pipeline, name="trigger_pipeline"),
    path("cron/run/", cron_trigger, name="cron_trigger"),
    path("job/<int:job_id>/", job_detail, name="job_detail"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
