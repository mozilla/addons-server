from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scanners', '0070_add_patch_results_permission_to_group'),
    ]

    operations = [
        migrations.AlterField(
            model_name='scannerqueryresult',
            name='scanner',
            field=models.PositiveSmallIntegerField(
                choices=[
                    (1, 'customs (legacy)'),
                    (2, 'wat'),
                    (3, 'yara'),
                    (4, 'mad'),
                    (5, 'narc'),
                    (6, 'webhook'),
                ]
            ),
        ),
        migrations.AlterField(
            model_name='scannerresult',
            name='scanner',
            field=models.PositiveSmallIntegerField(
                choices=[
                    (1, 'customs (legacy)'),
                    (2, 'wat'),
                    (3, 'yara'),
                    (4, 'mad'),
                    (5, 'narc'),
                    (6, 'webhook'),
                ]
            ),
        ),
        migrations.AlterField(
            model_name='scannerrule',
            name='scanner',
            field=models.PositiveSmallIntegerField(
                choices=[
                    (1, 'customs (legacy)'),
                    (2, 'wat'),
                    (3, 'yara'),
                    (4, 'mad'),
                    (5, 'narc'),
                    (6, 'webhook'),
                ]
            ),
        ),
    ]
