import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0003_companyprofile_application_start_date"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserPreference",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "language",
                    models.CharField(
                        choices=[
                            ("id", "Bahasa Indonesia"),
                            ("en", "English"),
                            ("ko", "한국어"),
                        ],
                        default="id",
                        max_length=5,
                    ),
                ),
                (
                    "theme",
                    models.CharField(
                        choices=[("light", "Light"), ("dark", "Dark")],
                        default="light",
                        max_length=5,
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ui_preference",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="userpreference",
            constraint=models.CheckConstraint(
                condition=models.Q(("language__in", ["id", "en", "ko"])),
                name="user_preference_language_allowed",
            ),
        ),
        migrations.AddConstraint(
            model_name="userpreference",
            constraint=models.CheckConstraint(
                condition=models.Q(("theme__in", ["light", "dark"])),
                name="user_preference_theme_allowed",
            ),
        ),
    ]
