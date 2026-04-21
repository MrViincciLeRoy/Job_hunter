from django.db import models


class CV(models.Model):
    pdf = models.FileField(upload_to="cv/", blank=True, null=True)  # kept for compat
    pdf_data = models.BinaryField(blank=True, null=True)             # actual persistent storage
    pdf_filename = models.CharField(max_length=255, blank=True)
    parsed_data = models.JSONField(default=dict)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.parsed_data.get("name", "CV") + f" ({self.uploaded_at.date()})"

    def get_pdf_bytes(self) -> bytes | None:
        if self.pdf_data:
            return bytes(self.pdf_data)
        # fallback: try filesystem (local dev)
        try:
            if self.pdf and self.pdf.path:
                with open(self.pdf.path, "rb") as f:
                    return f.read()
        except Exception:
            pass
        return None
