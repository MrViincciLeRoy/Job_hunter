from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scraper", "0002_job_extra_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="docs_required",
            field=models.TextField(blank=True),
        ),
    ]
