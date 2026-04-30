"""
Migration: add nullable user FK to CV, Job, Application.
Run AFTER accounts 0001_initial.
After migrating, run:
  python manage.py assign_existing_data
to assign all existing rows to the first superuser.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("cv",      "0002_cv_pdf_data"),
        ("scraper", "0003_job_docs_required"),
        ("mailer",  "0001_initial"),
        ("accounts","0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # CV.user
        migrations.AddField(
            model_name="cv",
            name="user",
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="cvs",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # Job.user
        migrations.AddField(
            model_name="job",
            name="user",
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="jobs",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # Application.user
        migrations.AddField(
            model_name="application",
            name="user",
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="applications",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
