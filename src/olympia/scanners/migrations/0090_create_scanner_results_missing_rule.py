from django.db import migrations

from olympia.amo.decorators import use_primary_db
from olympia.constants.scanners import (
    NO_ACTION,
    SCANNER_RESULTS_MISSING_RULE_NAME,
    WEBHOOK,
)


@use_primary_db
def create_rule(apps, schema_editor):
    ScannerRule = apps.get_model('scanners', 'ScannerRule')
    ScannerRule.objects.get_or_create(
        name=SCANNER_RESULTS_MISSING_RULE_NAME,
        scanner=WEBHOOK,
        defaults={
            'action': NO_ACTION,
            'is_active': True,
            'pretty_name': 'Scanner results missing',
            'description': (
                'Auto-created rule for when a scanner never sent its results. '
                'Do not disable.'
            ),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ('scanners', '0089_alter_scannerwebhook_name'),
    ]

    operations = [migrations.RunPython(create_rule)]
