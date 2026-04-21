from django.contrib import admin
from .models import Application


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ["job", "status", "sent_at"]
    ordering = ["-sent_at"]
