from django.contrib.postgres.indexes import GinIndex
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0001_initial"),
        ("core", "0002_pg_trgm"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="transaction",
            index=GinIndex(
                fields=["notes"],
                name="txn_notes_gin_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ),
    ]
