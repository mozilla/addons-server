# Generated by Django 3.2.13 on 2022-05-30 16:39

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('devhub', '0003_auto_20220413_1016'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='blogpost',
            options={'ordering': ('-date_posted',)},
        ),
    ]
