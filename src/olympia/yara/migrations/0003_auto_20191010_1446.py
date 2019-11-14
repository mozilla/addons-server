from django.db import migrations
from django.db.models import Case, Value, When


def backfill_has_matches(apps, schema_editor):
    YaraResult = apps.get_model('yara', 'YaraResult')
    YaraResult.objects.filter(has_matches=None).update(
        has_matches=Case(
            When(matches='[]', then=Value(False)),
            default=Value(True)
        )
    )


class Migration(migrations.Migration):

    dependencies = [
        ('yara', '0002_auto_20191009_1239'),
    ]

    operations = [
        migrations.RunPython(backfill_has_matches),
    ]
