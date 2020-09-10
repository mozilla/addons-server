# Generated by Django 2.2.14 on 2020-08-19 09:51

from django.db import migrations

from olympia import amo
from olympia.addons.tasks import index_addons
from olympia.constants.promoted import RECOMMENDED


@amo.decorators.use_primary_db
def make_recommended_firefox_only(apps, schema_editor# Generated by Django 2.2.14 on 2020-08-19 09:51

from django.db import migrations

from olympia import amo
from olympia.addons.tasks import index_addons
from olympia.constants.promoted import RECOMMENDED


@amo.decorators.use_primary_db
def make_recommended_firefox_only(apps, schema_editor):
    PromotedAddon = apps.get_model('promoted', 'PromotedAddon')
    qs = PromotedAddon.objects.filter(
        group_id=RECOMMENDED.id, application_id=None)
    for promo in qs:
        promo.application_id = amo.FIREFOX.id
        promo.save()
    index_addons.delay([promoted.addon_id for promoted in qs])


@amo.decorators.use_primary_db
def make_recommended_all_apps(apps, schema_editor):
    PromotedAddon = apps.get_model('promoted', 'PromotedAddon')
    qs = PromotedAddon.objects.filter(
        group_id=RECOMMENDED.id, application_id=amo.FIREFOX.id)
    for promo in qs:
        promo.application_id = None
        promo.save()
    index_addons.delay([promoted.addon_id for promoted in qs])


class Migration(migrations.Migration):

    dependencies = [
        ('promoted', '0005_auto_20200803_1214'),
    ]

    operations = [
        migrations.RunPython(
            make_recommended_firefox_only,
            reverse_code=make_recommended_all_apps),
    ]

    PromotedAddon = apps.get_model('promoted', 'PromotedAddon')
    qs = PromotedAddon.objects.filter(
        group_id=RECOMMENDED.id, application_id=None)
    for promo in qs:
        promo.application_id = amo.FIREFOX.id
        promo.save()
    index_addons.delay([promoted.addon_id for promoted in qs])


class Migration(migrations.Migration):

    dependencies = [
        ('promoted', '0005_auto_20200803_1214'),
    ]

    operations = [
        migrations.RunPython(make_recommended_firefox_only)
    ]
