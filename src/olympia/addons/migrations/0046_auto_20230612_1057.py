# Generated by Django 3.2.18 on 2023-06-12 10:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('addons', '0045_addonbrowsermapping'),
    ]

    operations = [
        migrations.AlterField(
            model_name='addonreviewerflags',
            name='needs_admin_code_review',
            field=models.BooleanField(default=False, null=True),
        ),
        migrations.AlterField(
            model_name='addonreviewerflags',
            name='needs_admin_content_review',
            field=models.BooleanField(default=False, null=True),
        ),
    ]
