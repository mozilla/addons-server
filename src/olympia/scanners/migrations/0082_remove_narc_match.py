from django.db import migrations

from olympia.amo.decorators import use_primary_db
from olympia.constants.scanners import NARC


@use_primary_db
def remove_match_from_narc_results(apps, schema_editor):
    ScannerResult = apps.get_model('scanners', 'ScannerResult')
    qs = ScannerResult.objects.filter(scanner=NARC).exclude(results=None)
    for instance in qs:
        changed = False
        for result in instance.results:
            meta = result.get('meta')
            if meta:
                if 'match' in meta:
                    del meta['match']
                    changed = True
        if changed:
            instance.save(update_fields=['results'])


class Migration(migrations.Migration):

    dependencies = [
        ('scanners', '0081_scannerwebhookevent_is_active'),
    ]

    operations = [migrations.RunPython(remove_match_from_narc_results)]
