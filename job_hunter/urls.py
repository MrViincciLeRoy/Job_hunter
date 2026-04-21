from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from apps.scraper.views import dashboard
from apps.cv.views import upload_cv

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", dashboard, name="dashboard"),
    path("upload-cv/", upload_cv, name="upload_cv"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
