from django.core.management.base import BaseCommand
from apps.scraper.models import Job
from apps.cv.models import CV
from apps.matcher.matcher import match_job_to_cv


class Command(BaseCommand):
    help = "Score unmatched jobs against active CV"

    def handle(self, *args, **options):
        cv = CV.objects.filter(active=True).last()
        if not cv:
            self.stderr.write("No active CV.")
            return

        jobs = Job.objects.filter(match_score=0)
        self.stdout.write(f"Scoring {jobs.count()} jobs...")

        for job in jobs:
            score = match_job_to_cv(
                cv.parsed_data,
                {"title": job.title, "description": job.description},
            )
            job.match_score = score
            job.save(update_fields=["match_score"])
            self.stdout.write(f"  {score:>3}/100 — {job.title} @ {job.company}")

        self.stdout.write(self.style.SUCCESS("Done."))
