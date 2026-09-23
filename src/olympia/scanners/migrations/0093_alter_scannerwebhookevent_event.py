from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('scanners', '0092_alter_scannerwebhookevent_event'),
    ]

    operations = [
        migrations.AlterField(
            model_name='scannerwebhookevent',
            name='event',
            field=models.PositiveSmallIntegerField(
                choices=[
                    (1, 'during_validation'),
                    (2, 'on_source_code_uploaded'),
                    (3, 'on_version_created'),
                    (4, 'push'),
                    (5, 'on_listing_changed'),
                    (6, 'on_version_scanned'),
                ]
            ),
        ),
    ]
