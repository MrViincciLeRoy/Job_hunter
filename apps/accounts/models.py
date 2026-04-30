from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    user          = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    photo         = models.BinaryField(blank=True, null=True)
    photo_mime    = models.CharField(max_length=50, blank=True)
    phone         = models.CharField(max_length=30, blank=True)
    location      = models.CharField(max_length=100, blank=True)
    bio           = models.TextField(blank=True)
    github_url    = models.URLField(blank=True)
    portfolio_url = models.URLField(blank=True)
    linkedin_url  = models.URLField(blank=True)
    id_number     = models.CharField(max_length=20, blank=True)   # SA ID
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile: {self.user.email}"


DOC_TYPES = [
    ("cv",           "CV / Resume"),
    ("cover_letter", "Cover Letter Template"),
    ("certificate",  "Certificate / Qualification"),
    ("id_document",  "ID Document"),
    ("z83",          "Z83 Application Form"),
    ("other",        "Other Document"),
]


class UserDocument(models.Model):
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name="documents")
    doc_type    = models.CharField(max_length=30, choices=DOC_TYPES)
    label       = models.CharField(max_length=255)          # user-given name
    file_data   = models.BinaryField()
    file_name   = models.CharField(max_length=255)
    mime_type   = models.CharField(max_length=100, blank=True)
    file_size   = models.IntegerField(default=0)            # bytes
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_primary  = models.BooleanField(default=False)        # primary CV flag

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.get_doc_type_display()} — {self.label} ({self.user.email})"

    def size_display(self):
        kb = self.file_size / 1024
        if kb > 1024:
            return f"{kb/1024:.1f} MB"
        return f"{kb:.0f} KB"
