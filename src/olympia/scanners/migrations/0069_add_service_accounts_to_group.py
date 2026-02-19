from django.db import migrations

from olympia.amo.decorators import use_primary_db
from olympia.constants.scanners import SCANNER_SERVICE_ACCOUNTS_GROUP


@use_primary_db
def add_service_accounts_to_group(apps, schema_editor):
    Group = apps.get_model('access', 'Group')
    GroupUser = apps.get_model('access', 'GroupUser')
    UserProfile = apps.get_model('users', 'UserProfile')

    group = Group.objects.get(name=SCANNER_SERVICE_ACCOUNTS_GROUP)

    service_accounts = UserProfile.objects.filter(
        username__startswith='service-account-',
        fxa_id__isnull=True,
        email__isnull=True,
    )

    for user in service_accounts:
        GroupUser.objects.get_or_create(group=group, user=user)


class Migration(migrations.Migration):

    dependencies = [
        ('scanners', '0068_create_scanner_service_accounts_group'),
    ]

    operations = [migrations.RunPython(add_service_accounts_to_group)]
