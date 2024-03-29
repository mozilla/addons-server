# Generated by Django 3.2.14 on 2022-08-03 09:48

from django.db import migrations, models


def set_missing_guid(apps, schema_editor):
    AbuseReport = apps.get_model('abuse', 'AbuseReport')
    for report in AbuseReport.unfiltered.filter(guid__isnull=True, user_id__isnull=True):
        if (addon := getattr(report, 'addon', None)) and addon.guid:
            # Try to associate the report with a guid, if we have one.
            report.guid = addon.guid
            report.save()
        else:
            # Otherwise there isn't anything we can do, so delete the report.
            report.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('abuse', '0006_auto_20210813_0941'),
    ]

    operations = [
        migrations.RunPython(set_missing_guid),
        migrations.RemoveField(
            model_name='abusereport',
            name='addon',
        ),
        migrations.AddConstraint(
            model_name='abusereport',
            constraint=models.CheckConstraint(check=models.Q(models.Q(models.Q(('guid', ''), _negated=True), ('guid__isnull', False), ('user__isnull', True)), models.Q(('guid__isnull', True), ('user__isnull', False)), _connector='OR'), name='just_one_of_guid_and_user_must_be_set'),
        ),
    ]
