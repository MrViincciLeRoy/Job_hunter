from django.core.management.base import BaseCommand
from apps.scraper.scrapers.jobspy_scraper import scrape_linkedin, scrape_indeed
from apps.scraper.scrapers.pnet import scrape_pnet
from apps.scraper.scrapers.careerjunction import scrape_careerjunction
from apps.scraper.scrapers.careers24 import scrape_careers24
from apps.scraper.scrapers.jobmail import scrape_jobmail
from apps.scraper.scrapers.gumtree import scrape_gumtree
from apps.scraper.models import Job
from apps.cv.models import CV

# Ordered by email likelihood — high-yield platforms first
SCRAPERS = [
    ("PNet",           scrape_pnet,          "high"),
    ("CareerJunction", scrape_careerjunction, "high"),
    ("Careers24",      scrape_careers24,      "high"),
    ("JobMail",        scrape_jobmail,        "high"),
    ("Gumtree",        scrape_gumtree,        "medium"),
    ("LinkedIn",       scrape_linkedin,       "low"),
    ("Indeed",         scrape_indeed,         "low"),
]


class Command(BaseCommand):
    help = "Scrape jobs from all platforms"

    def add_arguments(self, parser):
        parser.add_argument("--keywords", type=str, default=None)
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--email-only", action="store_true",
                            help="Only run high email-likelihood scrapers")

    def handle(self, *args, **options):
        cv = CV.objects.filter(active=True).last()
        if not cv:
            self.stderr.write("No active CV. Upload one first via /upload-cv/")
            return

        keywords = options.get("keywords")
        if not keywords:
            skills = cv.parsed_data.get("skills", [])
            keywords = " ".join(skills[:3]) if skills else "developer"

        limit = options["limit"]
        email_only = options["email_only"]
        self.stdout.write(f"Searching: '{keywords}' | limit={limit} | email_only={email_only}")

        scrapers = [s for s in SCRAPERS if not email_only or s[2] == "high"]

        all_jobs = []
        for name, fn, tier in scrapers:
            try:
                self.stdout.write(f"  [{tier.upper()}] {name}...", ending="")
                results = fn(keywords, limit=limit)
                count = len(results)
                email_count = sum(1 for j in results if j.get("apply_email"))
                self.stdout.write(f" {count} jobs, {email_count} with email")
                all_jobs += results
            except Exception as e:
                self.stdout.write(self.style.ERROR(f" failed: {e}"))

        created = skipped = 0
        for j in all_jobs:
            if not j.get("title"):
                continue
            _, new = Job.objects.get_or_create(
                title=j["title"],
                company=j.get("company", ""),
                platform=j["platform"],
                defaults={
                    "location": j.get("location", ""),
                    "description": j.get("description", ""),
                    "url": j.get("url", ""),
                    "apply_email": j.get("apply_email", ""),
                },
            )
            if new:
                created += 1
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {created} new jobs saved, {skipped} already existed."
        ))
