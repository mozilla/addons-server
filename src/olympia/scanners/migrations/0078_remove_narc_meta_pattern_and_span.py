from django.db import migrations

from olympia.amo.decorators import use_primary_db
from olympia.constants.scanners import NARC


@use_primary_db
def remove_pattern_and_span_from_narc_results(apps, schema_editor):
    ScannerResult = apps.get_model('scanners', 'ScannerResult')
    qs = ScannerResult.objects.filter(scanner=NARC).exclude(results=None)
    for instance in qs:
        changed = False
        for result in instance.results:
            meta = result.get('meta')
            if meta:
                if 'pattern' in meta:
                    del meta['pattern']
                    changed = True
                if 'span' in meta:
                    del meta['span']
                    changed = True
        if changed:
            instance.save(update_fields=['results'])


class Migration(migrations.Migration):

    dependencies = [
        ('scanners', '0077_create_annotations_scanner_rule_for_webhook'),
    ]

    operations = [migrations.RunPython(remove_pattern_and_span_from_narc_results)]
