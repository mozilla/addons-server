# Generated by Django 2.2.10 on 2020-02-25 11:10

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scanners', '0026_auto_20200217_1528'),
    ]

    operations = [
        migrations.AddField(
            model_name='scannerqueryrule',
            name='group_result_id',
            field=models.UUIDField(default=None, null=True),
        ),
        migrations.AddField(
            model_name='scannerqueryrule',
            name='task_count',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
