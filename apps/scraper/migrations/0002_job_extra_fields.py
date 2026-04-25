from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scraper", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="salary",
            field=models.CharField(max_length=255, blank=True),
        ),
        migrations.AddField(
            model_name="job",
            name="job_type",
            field=models.CharField(max_length=100, blank=True),
        ),
        migrations.AddField(
            model_name="job",
            name="how_to_apply",
            field=models.TextField(blank=True),
        ),
    ]
