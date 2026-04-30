"""
python manage.py assign_existing_data

Assigns all CV, Job, and Application rows that have no user
to the first superuser. Run once after applying the 0002_add_user_fk migration.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from apps.cv.models import CV
from apps.scraper.models import Job
from apps.mailer.models import Application


class Command(BaseCommand):
    help = "Assign existing un-owned data to the first superuser"

    def handle(self, *args, **options):
        superuser = User.objects.filter(is_superuser=True).first()
        if not superuser:
            self.stderr.write("No superuser found. Create one first: python manage.py createsuperuser")
            return

        cv_count  = CV.objects.filter(user__isnull=True).update(user=superuser)
        job_count = Job.objects.filter(user__isnull=True).update(user=superuser)
        app_count = Application.objects.filter(user__isnull=True).update(user=superuser)

        self.stdout.write(self.style.SUCCESS(
            f"Assigned to {superuser.email}:\n"
            f"  CVs:          {cv_count}\n"
            f"  Jobs:         {job_count}\n"
            f"  Applications: {app_count}"
        ))
