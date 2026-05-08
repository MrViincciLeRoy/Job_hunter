import os
from django.db import models
from django.core.validators import FileExtensionValidator


class DocumentType(models.TextChoices):
    CV               = "cv",               "CV / Resume"
    COVER_LETTER     = "cover_letter",     "Cover Letter"
    ID_DOCUMENT      = "id_document",      "ID Document"
    MATRIC           = "matric",           "Matric Certificate"
    QUALIFICATIONS   = "qualifications",   "Qualifications / Certificates"
    DRIVERS_LICENCE  = "drivers_licence",  "Driver's Licence"
    POLICE_CLEARANCE = "police_clearance", "Police Clearance Certificate"
    REFERENCES       = "references",       "References"
    PROOF_OF_ADDRESS = "proof_of_address", "Proof of Address"
    BANK_DETAILS     = "bank_details",     "Bank Details"
    Z83              = "z83",              "Z83 Form"
    CERTIFIED_COPIES = "certified_copies", "Certified Copies"
    SAQA             = "saqa",             "SAQA Verification"
    PROFESSIONAL_REG = "professional_reg", "Professional Body Registration"
    PORTFOLIO        = "portfolio",        "Portfolio / Work Samples"
    TRANSCRIPT       = "transcript",       "Academic Transcript"
    OTHER            = "other",            "Other"


def document_upload_path(instance, filename):
    return f"documents/{instance.doc_type}/{filename}"


# Maps file extension → MIME-like string used by the template icon logic
_EXT_MIME = {
    "pdf":  "application/pdf",
    "doc":  "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "png":  "image/png",
}


class Document(models.Model):
    doc_type    = models.CharField(max_length=50, choices=DocumentType.choices)
    label       = models.CharField(max_length=255, blank=True)
    file        = models.FileField(
        upload_to=document_upload_path,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "doc", "docx", "jpg", "jpeg", "png"])],
    )
    active      = models.BooleanField(default=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    note        = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.get_doc_type_display()} — {self.display_label}"

    # ── existing helpers ──────────────────────────────────────────────────────

    @property
    def display_label(self):
        return self.label or self.filename

    @property
    def filename(self):
        return os.path.basename(self.file.name)

    def get_bytes(self):
        try:
            with self.file.open("rb") as f:
                return f.read()
        except Exception:
            return None

    # ── new helpers expected by accounts/documents.html ──────────────────────

    @property
    def file_name(self):
        """Alias so the template can use doc.file_name."""
        return self.filename

    @property
    def is_primary(self):
        """True when this is the active record for its type (used as 'Primary CV' badge)."""
        return self.active

    @property
    def mime_type(self):
        ext = self.filename.rsplit(".", 1)[-1].lower() if "." in self.filename else ""
        return _EXT_MIME.get(ext, "application/octet-stream")

    @property
    def size_display(self):
        """Human-readable file size, e.g. '245 KB'. Returns '' if the file is missing."""
        try:
            size = self.file.size          # raises if storage can't stat the file
        except Exception:
            return ""
        if size < 1024:
            return f"{size} B"
        if size < 1024 ** 2:
            return f"{size // 1024} KB"
        return f"{size / 1024 ** 2:.1f} MB"