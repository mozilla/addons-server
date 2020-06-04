# Generated by Django 2.2.12 on 2020-06-04 13:19

from django.db import migrations

from olympia.constants.base import (
    ADDON_DICT,
    ADDON_EXTENSION,
    ADDON_LPAPP,
    ADDON_STATICTHEME,
)


def delete_old_categories(apps, schema_editor):
    Category = apps.get_model('addons', 'Category')
    Category.objects.exclude(
        type__in=(ADDON_DICT, ADDON_EXTENSION, ADDON_LPAPP, ADDON_STATICTHEME)
    ).delete()


class Migration(migrations.Migration):

    dependencies = [('addons', '0009_auto_20200603_1251')]

    operations = [migrations.RunPython(delete_old_categories)]
