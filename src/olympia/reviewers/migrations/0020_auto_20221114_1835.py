# Generated by Django 3.2.16 on 2022-11-14 18:35

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reviewers', '0019_reviewactionreason_canned_response'),
    ]

    operations = [
        migrations.AlterField(
            model_name='whiteboard',
            name='private',
            field=models.TextField(blank=True, max_length=100000),
        ),
        migrations.AlterField(
            model_name='whiteboard',
            name='public',
            field=models.TextField(blank=True, max_length=100000),
        ),
    ]
