# Generated by Django 4.2.16 on 2024-09-27 18:10

from django.db import migrations


def create_waffle_flag(apps, schema_editor):
    Flag = apps.get_model('waffle', 'Flag')
    Flag.objects.get_or_create(  
        name='enable-submissions',  
        defaults={'everyone': True},  
    )  

class Migration(migrations.Migration):

    dependencies = [
        ('addons', '0051_remove_accessibility'),
    ]

    operations = [migrations.RunPython(create_waffle_flag)]
