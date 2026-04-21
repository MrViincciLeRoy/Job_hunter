from django.core.management.base import BaseCommand
from apps.scraper.models import Job
from apps.scraper.scrapers.spider import spider_url, email_likelihood_score


class Command(BaseCommand):
    help = "Spider job URLs to extract emails — high-yield platforms first"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--job-id", type=int)
        parser.add_argument("--delete-no-email", action="store_true",
                            help="Delete jobs where spider finds no email")

    def handle(self, *args, **options):
        if options.get("job_id"):
            jobs = list(Job.objects.filter(pk=options["job_id"]))
        elif options["all"]:
            jobs = list(Job.objects.exclude(url=""))
        else:
            jobs = list(Job.objects.filter(apply_email="").exclude(url=""))

        # Sort by email likelihood — spider most promising first
        jobs.sort(key=lambda j: email_likelihood_score(j.platform, j.url), reverse=True)
        jobs = jobs[:options["limit"]]

        self.stdout.write(f"Spidering {len(jobs)} jobs (sorted by email likelihood)...")

        found = deleted = 0
        for job in jobs:
            score = email_likelihood_score(job.platform, job.url)
            self.stdout.write(
                f"  [score={score}] {job.platform} · {job.title} @ {job.company}... ",
                ending=""
            )

            result = spider_url(job.url)

            if result["error"]:
                self.stdout.write(self.style.WARNING(f"✗ {result['error']}"))
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
                self.stdout.write(self.style.SUCCESS(f"✓ {job.apply_email or 'desc updated'}"))
            elif options["delete_no_email"] and not job.apply_email:
                job.delete()
                deleted += 1
                self.stdout.write(self.style.ERROR("✗ deleted (no email)"))
            else:
                self.stdout.write("— no new data")

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {found} emails found, {deleted} jobs deleted."
        ))
