# Generated by Django 3.2.13 on 2022-05-30 16:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('files', '0021_auto_20220503_1855'),
    ]

    operations = [
        migrations.AlterField(
            model_name='fileupload',
            name='source',
            field=models.PositiveSmallIntegerField(choices=[(1, 'Developer Hub'), (2, 'Signing API'), (3, 'Add-on API'), (4, 'Automatically generated by AMO')]),
        ),
    ]
