from django.db import migrations


def remove_waffle_switch(apps, schema_editor):
    Switch = apps.get_model('waffle', 'Switch')

    Switch.objects.filter(name='enable-wat').delete()


class Migration(migrations.Migration):

    dependencies = [('scanners', '0045_auto_20210604_1340')]

    operations = [migrations.RunPython(remove_waffle_switch)]
