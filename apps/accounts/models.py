from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    user             = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    photo            = models.BinaryField(blank=True, null=True)
    photo_mime       = models.CharField(max_length=50, blank=True)
    phone            = models.CharField(max_length=30, blank=True)
    location         = models.CharField(max_length=100, blank=True)
    bio              = models.TextField(blank=True)
    github_url       = models.URLField(blank=True)
    portfolio_url    = models.URLField(blank=True)
    linkedin_url     = models.URLField(blank=True)
    id_number        = models.CharField(max_length=20, blank=True)
    date_of_birth    = models.DateField(null=True, blank=True)
    occupation       = models.CharField(max_length=100, blank=True)
    years_experience = models.CharField(max_length=20, blank=True)
    onboarding_done  = models.BooleanField(default=False)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

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
    label       = models.CharField(max_length=255)
    file_data   = models.BinaryField()
    file_name   = models.CharField(max_length=255)
    mime_type   = models.CharField(max_length=100, blank=True)
    file_size   = models.IntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_primary  = models.BooleanField(default=False)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.get_doc_type_display()} — {self.label} ({self.user.email})"

    def size_display(self):
        kb = self.file_size / 1024
        return f"{kb/1024:.1f} MB" if kb > 1024 else f"{kb:.0f} KB"


class WorkExperience(models.Model):
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name="work_experiences")
    job_title   = models.CharField(max_length=150)
    company     = models.CharField(max_length=150)
    location    = models.CharField(max_length=100, blank=True)
    start_date  = models.DateField()
    end_date    = models.DateField(null=True, blank=True)
    is_current  = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.job_title} at {self.company}"

    def duration(self):
        from datetime import date
        end = date.today() if self.is_current else self.end_date
        if not end:
            return ""
        months = (end.year - self.start_date.year) * 12 + (end.month - self.start_date.month)
        if months < 12:
            return f"{months} mo"
        y, m = divmod(months, 12)
        return f"{y} yr {m} mo" if m else f"{y} yr"


NQF_LEVELS = [
    ("",    "Select NQF Level"),
    ("4",   "NQF 4 — Matric / Grade 12"),
    ("5",   "NQF 5 — Higher Certificate"),
    ("6",   "NQF 6 — Diploma / Advanced Certificate"),
    ("7",   "NQF 7 — Bachelor's Degree / Advanced Diploma"),
    ("8",   "NQF 8 — Honours / Postgrad Diploma"),
    ("9",   "NQF 9 — Master's Degree"),
    ("10",  "NQF 10 — Doctoral Degree"),
    ("other", "Other / International"),
]


class Education(models.Model):
    user          = models.ForeignKey(User, on_delete=models.CASCADE, related_name="education")
    institution   = models.CharField(max_length=200)
    qualification = models.CharField(max_length=200)
    field_of_study= models.CharField(max_length=150, blank=True)
    nqf_level     = models.CharField(max_length=10, choices=NQF_LEVELS, blank=True)
    start_year    = models.IntegerField()
    end_year      = models.IntegerField(null=True, blank=True)
    is_current    = models.BooleanField(default=False)
    description   = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_year"]

    def __str__(self):
        return f"{self.qualification} — {self.institution}"


SKILL_LEVELS = [
    ("beginner",     "Beginner"),
    ("intermediate", "Intermediate"),
    ("advanced",     "Advanced"),
    ("expert",       "Expert"),
]


class Skill(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="skills")
    name       = models.CharField(max_length=100)
    level      = models.CharField(max_length=20, choices=SKILL_LEVELS, default="intermediate")
    category   = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return f"{self.name} ({self.level})"


PROFICIENCY_LEVELS = [
    ("basic",        "Basic"),
    ("conversational","Conversational"),
    ("professional", "Professional"),
    ("native",       "Native / Fluent"),
]


class Language(models.Model):
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name="languages")
    name        = models.CharField(max_length=80)
    proficiency = models.CharField(max_length=20, choices=PROFICIENCY_LEVELS, default="professional")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} — {self.proficiency}"


class Reference(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="references")
    name       = models.CharField(max_length=150)
    company    = models.CharField(max_length=150, blank=True)
    position   = models.CharField(max_length=150, blank=True)
    email      = models.EmailField(blank=True)
    phone      = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.company})"


# Suggested platform presets — user can type anything they want
PLATFORM_SUGGESTIONS = [
    "LinkedIn", "GitHub", "Portfolio", "Twitter / X", "Instagram",
    "Facebook", "YouTube", "TikTok", "Behance", "Dribbble",
    "Stack Overflow", "Kaggle", "Medium", "Substack", "Personal Website",
    "Other",
]

PLATFORM_ICONS = {
    "linkedin":    "🔗",
    "github":      "🐙",
    "twitter":     "🐦",
    "instagram":   "📷",
    "facebook":    "📘",
    "youtube":     "▶️",
    "tiktok":      "🎵",
    "behance":     "🎨",
    "dribbble":    "🏀",
    "stackoverflow": "📚",
    "kaggle":      "📊",
    "medium":      "✍️",
    "substack":    "📬",
    "portfolio":   "🌐",
}


class SocialLink(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="social_links")
    platform   = models.CharField(max_length=80)
    url        = models.URLField(max_length=500)
    icon       = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["platform"]

    def __str__(self):
        return f"{self.platform}: {self.url}"

    def get_icon(self):
        if self.icon:
            return self.icon
        key = self.platform.lower().split("/")[0].strip()
        for k, v in PLATFORM_ICONS.items():
            if k in key:
                return v
        return "🔗"