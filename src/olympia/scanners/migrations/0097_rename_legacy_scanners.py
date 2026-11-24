from django.db import migrations, models


SCANNER_CHOICES = [
    (1, 'customs (legacy)'),
    (2, 'wat (legacy)'),
    (3, 'yara (legacy)'),
    (4, 'mad (legacy)'),
    (5, 'narc'),
    (6, 'webhook'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('scanners', '0096_alter_scannerrule_help_texts'),
    ]

    operations = [
        migrations.AlterField(
            model_name='scannerqueryresult',
            name='scanner',
            field=models.PositiveSmallIntegerField(choices=SCANNER_CHOICES),
        ),
        migrations.AlterField(
            model_name='scannerresult',
            name='scanner',
            field=models.PositiveSmallIntegerField(choices=SCANNER_CHOICES),
        ),
        migrations.AlterField(
            model_name='scannerrule',
            name='scanner',
            field=models.PositiveSmallIntegerField(choices=SCANNER_CHOICES),
        ),
    ]
