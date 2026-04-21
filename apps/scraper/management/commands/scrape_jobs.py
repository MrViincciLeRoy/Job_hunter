from django.core.management.base import BaseCommand
from apps.scraper.scrapers.jobspy_scraper import scrape_linkedin, scrape_indeed
from apps.scraper.scrapers.pnet import scrape_pnet
from apps.scraper.scrapers.careerjunction import scrape_careerjunction
from apps.scraper.models import Job
from apps.cv.models import CV


class Command(BaseCommand):
    help = "Scrape jobs from all platforms"

    def add_arguments(self, parser):
        parser.add_argument("--keywords", type=str, default=None)
        parser.add_argument("--limit", type=int, default=20)

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
        self.stdout.write(f"Searching: {keywords}")

        all_jobs = []
        for name, fn in [
            ("LinkedIn", scrape_linkedin),
            ("Indeed", scrape_indeed),
            ("PNet", scrape_pnet),
            ("CareerJunction", scrape_careerjunction),
        ]:
            try:
                self.stdout.write(f"  {name}...")
                all_jobs += fn(keywords, limit=limit)
            except Exception as e:
                self.stdout.write(f"  {name} failed: {e}")

        created = 0
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

        self.stdout.write(self.style.SUCCESS(f"Done. {created} new jobs saved."))
