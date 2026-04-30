from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/",          admin.site.urls),
    path("",                include("apps.dashboard.urls")),
    path("jobs/",           include("apps.scraper.urls")),
    path("upload-cv/",      include("apps.cv.urls")),
    path("credentials/",    include("apps.mailer.urls")),
    path("trigger/",        include("apps.pipeline.urls")),
    path("cron/",           include("apps.cron.urls")),
    path("job/",            include("apps.scraper.job_urls")),
    path("test/",           include("apps.scraper.test_urls")),

    # accounts app ? all live under /accounts/
    path("accounts/",       include(("apps.accounts.urls", "accounts"), namespace="accounts")),

    # allauth ? must come after our accounts/ so our views take priority
    path("accounts/",       include("allauth.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)