# Generated by Django 3.2.13 on 2022-05-30 16:39

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('es', '0002_alter_reindexing_site'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='reindexing',
            name='site',
        ),
    ]
