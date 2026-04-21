from django.core.management.base import BaseCommand
from apps.scraper.models import Job
from apps.scraper.scrapers.spider import spider_url


class Command(BaseCommand):
    help = "Spider job URLs to extract emails and extra info"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--all", action="store_true", help="Re-spider even jobs that already have emails")
        parser.add_argument("--job-id", type=int, help="Spider a single job by ID")

    def handle(self, *args, **options):
        if options.get("job_id"):
            jobs = Job.objects.filter(pk=options["job_id"])
        elif options["all"]:
            jobs = Job.objects.exclude(url="")
        else:
            jobs = Job.objects.filter(apply_email="").exclude(url="")

        jobs = jobs[:options["limit"]]
        self.stdout.write(f"Spidering {jobs.count()} jobs...")

        found = 0
        for job in jobs:
            self.stdout.write(f"  → {job.title} @ {job.company} ... ", ending="")
            result = spider_url(job.url)

            if result["error"]:
                self.stdout.write(self.style.ERROR(f"✗ {result['error']}"))
                continue

            updated = False

            if result["emails"] and not job.apply_email:
                job.apply_email = result["emails"][0]
                updated = True
                found += 1

            if result["description"] and len(result["description"]) > len(job.description):
                job.description = result["description"]
                updated = True

            if updated:
                job.save()
                email_str = job.apply_email or "no email"
                self.stdout.write(self.style.SUCCESS(f"✓ {email_str}"))
            else:
                self.stdout.write("— no new data")

        self.stdout.write(self.style.SUCCESS(f"\nDone. {found} new emails found."))
