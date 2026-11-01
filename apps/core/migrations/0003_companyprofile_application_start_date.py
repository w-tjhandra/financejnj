import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_pg_trgm"),
    ]

    operations = [
        migrations.AddField(
            model_name="companyprofile",
            name="application_start_date",
            field=models.DateField(default=django.utils.timezone.localdate),
        ),
    ]
