# Generated by Django 3.2.6 on 2021-09-06 13:56

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('files', '0014_auto_20210824_1722'),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE `files` DROP COLUMN `binary`,"
            " DROP COLUMN `binary_components`,"
            " DROP COLUMN `is_restart_required`;",
            state_operations=[
                migrations.RemoveField(
                    model_name='file',
                    name='binary',
                ),
                migrations.RemoveField(
                    model_name='file',
                    name='binary_components',
                ),
                migrations.RemoveField(
                    model_name='file',
                    name='is_restart_required',
                ),
            ],
        ),
    ]
