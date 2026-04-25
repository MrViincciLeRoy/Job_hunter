from django.db import models

PLATFORMS = [
    ("linkedin", "LinkedIn"),
    ("indeed", "Indeed"),
    ("pnet", "PNet"),
    ("careerjunction", "CareerJunction"),
    ("careerjunction_it", "CareerJunction IT"),
    ("careers24", "Careers24"),
    ("jobmail", "JobMail"),
    ("gumtree", "Gumtree"),
    ("dpsa", "DPSA"),
    ("sayouth", "SAYouth"),
    ("essa", "ESSA"),
    ("govza", "Gov.za"),
]


class Job(models.Model):
    title = models.CharField(max_length=255)
    company = models.CharField(max_length=255)
    location = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    platform = models.CharField(max_length=50, choices=PLATFORMS)
    url = models.TextField(blank=True)
    apply_email = models.CharField(max_length=255, blank=True)
    match_score = models.IntegerField(default=0)
    scraped_at = models.DateTimeField(auto_now_add=True)
    salary = models.CharField(max_length=255, blank=True)
    job_type = models.CharField(max_length=100, blank=True)
    how_to_apply = models.TextField(blank=True)

    class Meta:
        unique_together = ["title", "company", "platform"]

    def __str__(self):
        return f"{self.title} @ {self.company} [{self.platform}] — {self.match_score}%"
