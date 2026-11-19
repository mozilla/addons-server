from django.db import migrations

from olympia.amo.decorators import use_primary_db
from olympia.constants.scanners import (
    ANNOTATIONS_RULE_NAME,
    SCANNER_RESULTS_MISSING_RULE_NAME,
    WEBHOOK,
)


@use_primary_db
def remove_pretty_name(apps, schema_editor):
    ScannerRule = apps.get_model('scanners', 'ScannerRule')
    ScannerRule.objects.filter(
        name__in=(
            ANNOTATIONS_RULE_NAME,
            SCANNER_RESULTS_MISSING_RULE_NAME,
        ),
        scanner=WEBHOOK,
    ).update(pretty_name='')


class Migration(migrations.Migration):
    dependencies = [
        ('scanners', '0096_alter_scannerrule_help_texts'),
    ]

    operations = [migrations.RunPython(remove_pretty_name)]
