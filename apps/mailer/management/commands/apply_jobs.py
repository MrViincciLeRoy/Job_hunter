from django.core.management.base import BaseCommand
from apps.scraper.models import Job
from apps.cv.models import CV
from apps.mailer.models import Application
from apps.mailer.sender import send_application

BATCH_SIZE = 10


class Command(BaseCommand):
    help = "Email applications to matched jobs (max 10 per run)"

    def add_arguments(self, parser):
        parser.add_argument("--threshold", type=int, default=60)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=BATCH_SIZE)

    def handle(self, *args, **options):
        cv = CV.objects.filter(active=True).last()
        if not cv:
            self.stderr.write("No active CV.")
            return

        threshold = options["threshold"]
        dry_run = options["dry_run"]
        limit = options["limit"]

        jobs = (
            Job.objects.filter(match_score__gte=threshold)
            .exclude(apply_email="")
            .exclude(application__isnull=False)
            [:limit]
        )

        self.stdout.write(f"{jobs.count()} jobs eligible (score >= {threshold}, has email, not yet applied, capped at {limit})")

        pdf_bytes = cv.get_pdf_bytes()
        if not pdf_bytes:
            self.stderr.write("CV file missing — re-upload at /upload-cv/")
            return

        for job in jobs:
            if dry_run:
                self.stdout.write(f"[DRY RUN] {job.title} @ {job.company} → {job.apply_email} ({job.match_score}%)")
                continue

            try:
                ok, result = send_application(
                    cv.parsed_data,
                    {
                        "title": job.title,
                        "company": job.company,
                        "description": job.description,
                        "apply_email": job.apply_email,
                    },
                    pdf_bytes,
                    cv.pdf_filename or "CV.pdf",
                )

                if ok:
                    Application.objects.create(job=job, status="sent", cover_letter=result)
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Applied: {job.title} @ {job.company}"))
                else:
                    self.stdout.write(self.style.ERROR(f"  ✗ Failed: {job.title} — {result}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ✗ Exception: {job.title} — {e}"))
