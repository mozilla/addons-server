# Generated by Django 2.2.6 on 2019-10-23 09:08

from django.db import migrations


def add_matched_rules(apps, schema_editor):
    ScannerResult = apps.get_model('scanners', 'ScannerResult')
    for result in ScannerResult.objects.filter(has_matches=True):
        result.save()


class Migration(migrations.Migration):

    dependencies = [('scanners', '0009_auto_20191023_0906')]

    operations = [migrations.RunPython(add_matched_rules)]
