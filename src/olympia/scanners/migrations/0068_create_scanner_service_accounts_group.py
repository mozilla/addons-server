from django.db import migrations

from olympia.constants.scanners import SCANNER_SERVICE_ACCOUNTS_GROUP


def create_group(apps, schema_editor):
    Group = apps.get_model('access', 'Group')

    Group.objects.create(
        name=SCANNER_SERVICE_ACCOUNTS_GROUP,
        notes=(
            'This group is automatically managed. '
            'DO NOT manually edit this group or its members.'
        ),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('scanners', '0067_create_waffle_switch_for_yara_x'),
    ]

    operations = [migrations.RunPython(create_group)]
