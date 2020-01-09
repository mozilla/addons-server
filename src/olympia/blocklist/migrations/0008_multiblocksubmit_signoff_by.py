# Generated by Django 2.2.6 on 2020-01-09 11:55

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('blocklist', '0007_block_kinto_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='multiblocksubmit',
            name='signoff_by',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
    ]
