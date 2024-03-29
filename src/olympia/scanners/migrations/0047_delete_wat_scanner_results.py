# Generated by Django 3.2.13 on 2022-04-25 09:33

from django.db import migrations


def delete_scanner_results(apps, schema_editor):
    ScannerResult = apps.get_model('scanners', 'ScannerResult')

    # 2 = WAT
    ScannerResult.objects.filter(scanner=2).delete()


class Migration(migrations.Migration):

    dependencies = [('scanners', '0046_delete_waffle_switch')]

    operations = [migrations.RunPython(delete_scanner_results)]
