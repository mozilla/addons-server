# Generated by Django 4.2.16 on 2024-12-03 12:47

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('abuse', '0045_auto_20241120_1503'),
    ]

    operations = [
        migrations.AddField(
            model_name='contentdecision',
            name='override_of',
            field=models.OneToOneField(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='overridden_by', to='abuse.contentdecision'),
        ),
    ]
