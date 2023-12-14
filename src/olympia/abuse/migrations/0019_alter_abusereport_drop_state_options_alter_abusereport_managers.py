# Generated by Django 4.2.8 on 2023-12-12 17:59

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('abuse', '0018_cinderpolicy_cinderjob_policies'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='abusereport',
            options={},
        ),
        migrations.AlterModelManagers(
            name='abusereport',
            managers=[
            ],
        ),
        migrations.AlterField(
            model_name='abusereport',
            name='state',
            field=models.BooleanField(default=None, null=True)
        ),
    ]
