# Generated by Django 4.2.6 on 2023-10-24 09:51

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('abuse', '0013_alter_abusereport_reason'),
    ]

    operations = [
        migrations.AddField(
            model_name='abusereport',
            name='location',
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[
                    (None, 'None'),
                    (1, 'Add-on page on AMO'),
                    (2, 'Inside Add-on'),
                    (3, 'Both on AMO and inside Add-on'),
                ],
                default=None,
                null=True,
            ),
        ),
    ]
