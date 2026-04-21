from django.db import models


class CV(models.Model):
    pdf = models.FileField(upload_to="cv/")
    parsed_data = models.JSONField(default=dict)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.parsed_data.get("name", "CV") + f" ({self.uploaded_at.date()})"
