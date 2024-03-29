# Generated by Django 2.2.5 on 2019-09-12 15:18

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import olympia.amo.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('bandwagon', '0001_initial'),
        ('addons', '0002_addon_fk'),
        ('ratings', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('files', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='AkismetReport',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(blank=True, default=django.utils.timezone.now, editable=False)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('comment_type', models.CharField(max_length=255)),
                ('user_ip', models.CharField(max_length=255)),
                ('user_agent', models.CharField(max_length=255)),
                ('referrer', models.CharField(max_length=255)),
                ('user_name', models.CharField(max_length=255)),
                ('user_email', models.CharField(max_length=255)),
                ('user_homepage', models.CharField(max_length=255)),
                ('comment', models.TextField()),
                ('comment_modified', models.DateTimeField()),
                ('content_link', models.CharField(max_length=255, null=True)),
                ('content_modified', models.DateTimeField(null=True)),
                ('result', models.PositiveSmallIntegerField(choices=[(3, 'Unknown'), (0, 'Ham'), (1, 'Definite Spam'), (2, 'Maybe Spam')], null=True)),
                ('reported', models.BooleanField(default=False)),
                ('addon_instance', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='addons.Addon')),
                ('collection_instance', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='bandwagon.Collection')),
                ('rating_instance', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='ratings.Rating')),
                ('upload_instance', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='files.FileUpload')),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'akismet_reports',
            },
            bases=(olympia.amo.models.SaveUpdateMixin, models.Model),
        ),
    ]
