# Generated by Django 3.2.16 on 2023-01-07 00:47

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('versions', '0030_auto_20221122_1312'),
    ]

    operations = [
        migrations.AddField(
            model_name='version',
            name='due_date',
            field=models.DateTimeField(null=True),
        ),
    ]
