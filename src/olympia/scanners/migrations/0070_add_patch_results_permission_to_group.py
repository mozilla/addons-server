from django.db import migrations

from olympia.constants.scanners import SCANNER_SERVICE_ACCOUNTS_GROUP


def add_permission_to_group(apps, schema_editor):
    Group = apps.get_model('access', 'Group')

    group = Group.objects.get(name=SCANNER_SERVICE_ACCOUNTS_GROUP)
    rules = group.rules.split(',') if group.rules else []
    rules.append('Scanners:PatchResults')
    group.rules = ','.join(rules)
    group.save()


class Migration(migrations.Migration):

    dependencies = [
        ('scanners', '0069_add_service_accounts_to_group'),
    ]

    operations = [migrations.RunPython(add_permission_to_group)]
