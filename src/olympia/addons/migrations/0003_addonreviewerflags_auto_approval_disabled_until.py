# Generated by Django 2.2.6 on 2019-11-05 13:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('addons', '0002_addon_fk'),
    ]

    operations = [
        migrations.AddField(
            model_name='addonreviewerflags',
            name='auto_approval_delayed_until',
            field=models.DateTimeField(default=None, null=True),
        ),
    ]
