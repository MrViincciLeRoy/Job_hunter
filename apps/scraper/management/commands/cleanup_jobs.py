"""
cleanup_jobs — delete unapplied jobs from the database.

Keeps:
  - Jobs that have an Application record (already applied)

Deletes:
  - All other jobs (no application, regardless of email / match score)

Usage:
  python manage.py cleanup_jobs            # preview count, ask for confirmation
  python manage.py cleanup_jobs --confirm  # actually delete
  python manage.py cleanup_jobs --confirm --platform pnet   # one platform only
"""
from django.core.management.base import BaseCommand
from apps.scraper.models import Job
from apps.mailer.models import Application


class Command(BaseCommand):
    help = "Delete unapplied jobs from the database (keeps applied jobs)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually perform the deletion (without this flag, only counts are shown)",
        )
        parser.add_argument(
            "--platform",
            type=str,
            default=None,
            help="Limit cleanup to a specific platform slug (e.g. pnet, linkedin)",
        )

    def handle(self, *args, **options):
        confirm  = options["confirm"]
        platform = options.get("platform")

        applied_job_ids = set(Application.objects.values_list("job_id", flat=True))

        qs = Job.objects.exclude(pk__in=applied_job_ids)
        if platform:
            qs = qs.filter(platform__iexact=platform)

        total_to_delete = qs.count()
        total_applied   = Job.objects.filter(pk__in=applied_job_ids).count()
        total_jobs      = Job.objects.count()

        self.stdout.write(f"\n{'='*50}")
        self.stdout.write(f"  Total jobs in DB  : {total_jobs}")
        self.stdout.write(f"  Applied (keep)    : {total_applied}")
        self.stdout.write(f"  Unapplied (delete): {total_to_delete}")
        if platform:
            self.stdout.write(f"  Platform filter   : {platform}")
        self.stdout.write(f"{'='*50}\n")

        if total_to_delete == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to delete."))
            return

        if not confirm:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN — {total_to_delete} jobs would be deleted.\n"
                    "Run again with --confirm to actually delete."
                )
            )
            return

        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(
            f"✓ Deleted {deleted} unapplied jobs. "
            f"{total_applied} applied jobs remain."
        ))
