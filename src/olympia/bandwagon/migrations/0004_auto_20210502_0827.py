# Generated by Django 2.2.20 on 2021-05-02 08:27

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('bandwagon', '0003_auto_20210415_1620'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='collection',
            name='type_idx',
        ),
        migrations.RemoveField(
            model_name='collection',
            name='application',
        ),
        migrations.RemoveField(
            model_name='collection',
            name='nickname',
        ),
        migrations.RemoveField(
            model_name='collection',
            name='type',
        ),
    ]
