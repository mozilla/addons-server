from django.db import migrations

from olympia.core.db.migrations import CreateWaffleSwitch


class Migration(migrations.Migration):

    dependencies = [
        ('devhub', '0011_auto_20251015_1242'),
    ]

    operations = [
        CreateWaffleSwitch('enable-devhub-support-form'),
    ]
