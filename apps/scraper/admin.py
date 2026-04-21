from django.contrib import admin
from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ["title", "company", "platform", "match_score", "apply_email", "scraped_at"]
    list_filter = ["platform"]
    search_fields = ["title", "company"]
    ordering = ["-match_score"]
