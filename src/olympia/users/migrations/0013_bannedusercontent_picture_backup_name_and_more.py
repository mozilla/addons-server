# Generated by Django 4.2.7 on 2023-11-23 10:38

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0012_bannedusercontent"),
    ]

    operations = [
        migrations.AddField(
            model_name="bannedusercontent",
            name="picture_backup_name",
            field=models.CharField(blank=True, default=None, max_length=75, null=True),
        ),
        migrations.AddField(
            model_name="bannedusercontent",
            name="picture_type",
            field=models.CharField(blank=True, default=None, max_length=75, null=True),
        ),
    ]
