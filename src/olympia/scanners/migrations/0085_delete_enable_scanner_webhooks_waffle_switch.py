from django.db import migrations

from olympia.core.db.migrations import DeleteWaffleSwitch


class Migration(migrations.Migration):
    dependencies = [
        ('scanners', '0084_alter_scannerrule_action_alter_scannerrule_policy'),
    ]

    operations = [
        DeleteWaffleSwitch('enable-scanner-webhooks'),
    ]
