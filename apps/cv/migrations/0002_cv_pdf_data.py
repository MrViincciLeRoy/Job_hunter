from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cv", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="cv",
            name="pdf_data",
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cv",
            name="pdf_filename",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
