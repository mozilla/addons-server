# Generated by Django 3.2.16 on 2023-01-31 18:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('files', '0026_auto_20221104_1312'),
    ]

    operations = [
        migrations.AddField(
            model_name='file',
            name='approval_date',
            field=models.DateTimeField(null=True),
        ),
    ]
