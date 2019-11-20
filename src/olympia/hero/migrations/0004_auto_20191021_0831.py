# Generated by Django 2.2.5 on 2019-10-21 08:31

from django.db import migrations
import olympia.hero.models

from . import blank_featured_images


class Migration(migrations.Migration):

    dependencies = [
        ('hero', '0003_auto_20191001_0756'),
    ]

    operations = [
        migrations.RunPython(blank_featured_images),
        migrations.AlterField(
            model_name='primaryhero',
            name='image',
            field=olympia.hero.models.WidgetCharField(blank=True, choices=[('placeholder_a.jpg', 'placeholder_a.jpg'), ('placeholder_b.jpg', 'placeholder_b.jpg')], max_length=255),
        ),
    ]
