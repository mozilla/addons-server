from django.db import migrations

from olympia.core.db.migrations import DeleteWaffleSwitch


class Migration(migrations.Migration):
    dependencies = [
        ('files', '0037_fileupload_request_metadata'),
    ]

    operations = [DeleteWaffleSwitch('enable-mv3-submissions')]
