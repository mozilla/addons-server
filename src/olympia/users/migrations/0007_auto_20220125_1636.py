# Generated by Django 3.2.11 on 2022-01-25 16:36

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_auto_20210823_1454'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='userprofile',
            name='reviewer_name',
        ),
    ]
