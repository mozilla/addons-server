# Generated by Django 4.2.20 on 2025-03-25 19:03

from django.db import migrations, models
import django.db.models.deletion

def primary_hero_addon_up(apps, schema_editor):
    Hero = apps.get_model('hero', 'PrimaryHero')
    for hero in Hero.objects.all():
        hero.addon = hero.promoted_addon.addon
        hero.promoted_addon = None
        hero.save()

def primary_hero_addon_down(apps, schema_editor):
    Hero = apps.get_model('hero', 'PrimaryHero')
    for hero in Hero.objects.all():
        hero.promoted_addon = hero.addon.promotedaddon
        hero.save()

class Migration(migrations.Migration):

    dependencies = [
        ('addons', '0054_update_default_locale_es_to_es-es'),
        ('hero', '0019_alter_secondaryheromodule_icon'),
    ]

    operations = [
        # Make the promoted_addon field nullable
        migrations.AlterField(
            model_name='primaryhero',
            name='promoted_addon',
            field=models.OneToOneField(null=True, on_delete=django.db.models.deletion.CASCADE, to='promoted.promotedaddon'),
        ),
        # Add the addon field
        migrations.AddField(
            model_name='primaryhero',
            name='addon',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='addons.addon', null=True),
        ),
    ]
