# Generated by Django 2.2.16 on 2020-09-23 18:08

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blocklist', '0019_block_average_daily_users'),
    ]

    operations = [
        migrations.AlterField(
            model_name='blocklistsubmission',
            name='to_block',
            field=models.JSONField(default=list),
        ),
        migrations.AlterField(
            model_name='legacyimport',
            name='record',
            field=models.JSONField(default=dict),
        ),
    ]
