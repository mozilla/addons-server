from django.db import migrations

from olympia.core.db.migrations import DeleteWaffleSwitch


class Migration(migrations.Migration):
    dependencies = [
        ('scanners', '0090_create_scanner_results_missing_rule'),
    ]

    operations = [DeleteWaffleSwitch('use-yara-x')]
