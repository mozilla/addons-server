# Generated by Django 2.2.6 on 2019-10-23 14:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('versions', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='version',
            name='needs_human_review',
            field=models.BooleanField(null=True),
        ),
    ]
