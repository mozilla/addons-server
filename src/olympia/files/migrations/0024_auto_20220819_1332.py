# Generated by Django 3.2.15 on 2022-08-19 13:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('files', '0023_auto_20220803_1240'),
    ]

    operations = [
        migrations.AlterField(
            model_name='file',
            name='manifest_version',
            field=models.SmallIntegerField(choices=[(2, 'Manifest V2'), (3, 'Manifest V3')]),
        ),
    ]
