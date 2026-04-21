from django.db import models
from apps.scraper.models import Job


class Application(models.Model):
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name="application")
    sent_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=50, default="sent")
    cover_letter = models.TextField(blank=True)

    def __str__(self):
        return f"Applied: {self.job}"
