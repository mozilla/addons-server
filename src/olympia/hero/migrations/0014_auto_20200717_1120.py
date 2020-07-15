# Generated by Django 2.2.14 on 2020-07-17 11:20

from django.db import migrations, models
import django.db.models.deletion

import olympia.hero.models
from olympia.constants.promoted import NOT_PROMOTED, RECOMMENDED


def add_promoted_for_each_recommended(apps, schema_editor):
    DiscoveryItem = apps.get_model('discovery', 'DiscoveryItem')
    PromotedAddon = apps.get_model('promoted', 'PromotedAddon')
    for disco in DiscoveryItem.objects.all():
        group = RECOMMENDED if disco.recommendable else NOT_PROMOTED
        promoted = PromotedAddon.objects.create(
            addon=disco_addon.addon, group_id=group.id)
        if hasattr(disco, 'primaryhero'):
            disco.primaryhero.promoted_addon = promoted


class Migration(migrations.Migration):

    dependencies = [
        ('promoted', '0001_initial'),
        ('hero', '0013_auto_20200715_1751'),
    ]

    operations = [
        migrations.AddField(
            model_name='primaryhero',
            name='promoted_addon',
            field=models.OneToOneField(null=True, on_delete=django.db.models.deletion.CASCADE, to='promoted.PromotedAddon'),
        ),
        migrations.RunPython(add_promoted_for_each_recommended),
        migrations.AlterField(
            model_name='primaryhero',
            name='promoted_addon',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='promoted.PromotedAddon'),
        ),
        migrations.AlterField(
            model_name='primaryhero',
            name='disco_addon',
            field=models.OneToOneField(null=True, on_delete=django.db.models.deletion.CASCADE, to='discovery.DiscoveryItem'),
        ),
    ]
