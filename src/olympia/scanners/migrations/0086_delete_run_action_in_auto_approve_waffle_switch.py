from django.db import migrations

from olympia.core.db.migrations import DeleteWaffleSwitch


class Migration(migrations.Migration):
    dependencies = [
        ('scanners', '0085_delete_enable_scanner_webhooks_waffle_switch'),
    ]

    operations = [
        DeleteWaffleSwitch('run-action-in-auto-approve'),
    ]
