# Generated by Django 3.2.13 on 2022-04-26 20:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('es', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='reindexing',
            name='site',
            field=models.CharField(choices=[('amo', 'AMO')], max_length=3, null=True),
        ),
    ]
