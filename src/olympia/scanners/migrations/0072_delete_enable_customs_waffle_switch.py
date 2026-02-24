from django.db import migrations

from olympia.core.db.migrations import DeleteWaffleSwitch


class Migration(migrations.Migration):

    dependencies = [
        ('scanners', '0071_rename_customs_to_customs_legacy'),
    ]

    operations = [
        DeleteWaffleSwitch('enable-customs'),
    ]
