# Generated by Django 3.2.6 on 2021-08-26 13:28

from django.db import migrations, models


def set_tag_default(apps, schema_editor):
    Tag = apps.get_model('tags', 'Tag')
    Tag.objects.update(enable_for_random_shelf=True)


class Migration(migrations.Migration):

    dependencies = [
        ('tags', '0006_auto_20210813_0941'),
    ]

    operations = [
        migrations.AddField(
            model_name='tag',
            name='enable_for_random_shelf',
            field=models.BooleanField(default=True, null=True),
        ),
        migrations.RunPython(set_tag_default),
        migrations.AlterField(
            model_name='tag',
            name='enable_for_random_shelf',
            field=models.BooleanField(default=True),
        ),
    ]
