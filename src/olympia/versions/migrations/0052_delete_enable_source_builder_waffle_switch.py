from django.db import migrations

from olympia.core.db.migrations import DeleteWaffleSwitch


class Migration(migrations.Migration):

    dependencies = [
        ('versions', '0051_create_enable_source_builder_switch'),
    ]

    operations = [
        DeleteWaffleSwitch('enable-source-builder'),
    ]
