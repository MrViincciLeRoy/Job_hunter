from django.core.management.base import BaseCommand
from apps.scraper.models import Job
from apps.cv.models import CV
from apps.matcher.matcher import match_job_to_cv

BATCH_SIZE = 25


class Command(BaseCommand):
    help = "Score unmatched jobs against active CV (max 25 per run)"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=BATCH_SIZE)

    def handle(self, *args, **options):
        cv = CV.objects.filter(active=True).last()
        if not cv:
            self.stderr.write("No active CV.")
            return

        limit = options["limit"]
        jobs = Job.objects.filter(match_score=0)[:limit]
        total = Job.objects.filter(match_score=0).count()

        self.stdout.write(f"Scoring {jobs.count()} jobs (of {total} unscored, capped at {limit})...")

        for job in jobs:
            try:
                score = match_job_to_cv(
                    cv.parsed_data,
                    {"title": job.title, "description": job.description},
                )
                job.match_score = score
                job.save(update_fields=["match_score"])
                self.stdout.write(f"  {score:>3}/100 — {job.title} @ {job.company}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Failed: {job.title} — {e}"))

        remaining = total - jobs.count()
        if remaining > 0:
            self.stdout.write(self.style.WARNING(f"\n{remaining} jobs still unscored — run again tomorrow."))

        self.stdout.write(self.style.SUCCESS("Done."))
