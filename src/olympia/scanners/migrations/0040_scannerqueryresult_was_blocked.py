# Generated by Django 2.2.16 on 2020-10-16 13:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scanners', '0039_auto_20200923_1808'),
    ]

    operations = [
        migrations.AddField(
            model_name='scannerqueryresult',
            name='was_blocked',
            field=models.BooleanField(null=True),
        ),
    ]
