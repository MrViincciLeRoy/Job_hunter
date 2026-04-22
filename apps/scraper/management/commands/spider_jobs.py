from django.core.management.base import BaseCommand
from apps.scraper.models import Job
from apps.scraper.scrapers.spider import spider_many, email_likelihood_score


class Command(BaseCommand):
    help = "Spider job URLs to extract emails — async batch, high-yield platforms first"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--job-id", type=int)
        parser.add_argument("--delete-no-email", action="store_true")
        parser.add_argument("--concurrent", type=int, default=15,
                            help="Max concurrent async requests (default: 15)")

    def handle(self, *args, **options):
        if options.get("job_id"):
            jobs = list(Job.objects.filter(pk=options["job_id"]))
        elif options["all"]:
            jobs = list(Job.objects.exclude(url=""))
        else:
            jobs = list(Job.objects.filter(apply_email="").exclude(url=""))

        jobs.sort(key=lambda j: email_likelihood_score(j.platform, j.url), reverse=True)
        jobs = jobs[:options["limit"]]

        if not jobs:
            self.stdout.write("No jobs to spider.")
            return

        self.stdout.write(f"Spidering {len(jobs)} jobs async (concurrent={options['concurrent']})...")

        urls = [j.url for j in jobs]
        results = spider_many(urls, max_concurrent=options["concurrent"])

        found = deleted = 0
        for job in jobs:
            result = results.get(job.url, {})

            if not result or result.get("error"):
                self.stdout.write(self.style.WARNING(
                    f"  ✗ {job.platform} · {job.title[:50]} — {result.get('error', 'no result')}"
                ))
                continue

            updated = False
            if result["emails"] and not job.apply_email:
                job.apply_email = result["emails"][0]
                updated = True
                found += 1

            if result.get("description") and len(result["description"]) > len(job.description):
                job.description = result["description"]
                updated = True

            if updated:
                job.save()
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ {job.platform} · {job.title[:50]} — {job.apply_email or 'desc updated'}"
                ))
            elif options["delete_no_email"] and not job.apply_email:
                job.delete()
                deleted += 1
                self.stdout.write(self.style.ERROR(f"  ✗ {job.title[:50]} — deleted (no email)"))
            else:
                self.stdout.write(f"  — {job.title[:50]} no new data")

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {found} emails found, {deleted} jobs deleted."
        ))
