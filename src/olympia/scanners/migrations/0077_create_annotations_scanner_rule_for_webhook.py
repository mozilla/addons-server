from django.db import migrations

from olympia.amo.decorators import use_primary_db
from olympia.constants.scanners import ANNOTATIONS_RULE_NAME, NO_ACTION, WEBHOOK


@use_primary_db
def create_annotations_scanner_rule_for_webhook(apps, schema_editor):
    ScannerRule = apps.get_model('scanners', 'ScannerRule')
    ScannerRule.objects.get_or_create(
        name=ANNOTATIONS_RULE_NAME,
        scanner=WEBHOOK,
        defaults={
            'action': NO_ACTION,
            'is_active': True,
            'description': 'Auto-created rule for webhook annotations. Do not edit.',
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('scanners', '0076_remove_scannerresult_model_version'),
    ]

    operations = [migrations.RunPython(create_annotations_scanner_rule_for_webhook)]
