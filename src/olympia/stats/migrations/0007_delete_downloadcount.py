# Generated by Django 2.2.16 on 2020-10-06 16:00

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stats', '0006_create_switch_for_fenix_build_ids'),
    ]

    operations = [
        migrations.DeleteModel(
            name='DownloadCount',
        ),
    ]
