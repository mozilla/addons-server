# Generated by Django 2.2.5 on 2019-09-12 13:36

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import django_extensions.db.fields.json
import olympia.amo.fields
import olympia.amo.models
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('addons', '0001_initial'),
        ('applications', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('versions', '__first__'),
    ]

    operations = [
        migrations.CreateModel(
            name='File',
            fields=[
                ('created', models.DateTimeField(blank=True, default=django.utils.timezone.now, editable=False)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('id', olympia.amo.fields.PositiveAutoField(primary_key=True, serialize=False)),
                ('platform', models.PositiveIntegerField(choices=[(1, 'All Platforms'), (2, 'Linux'), (3, 'Mac OS X'), (5, 'Windows'), (7, 'Android')], db_column='platform_id', default=1)),
                ('filename', models.CharField(default='', max_length=255)),
                ('size', models.PositiveIntegerField(default=0)),
                ('hash', models.CharField(default='', max_length=255)),
                ('original_hash', models.CharField(default='', max_length=255)),
                ('status', models.PositiveSmallIntegerField(choices=[(1, 'Awaiting Review'), (4, 'Approved'), (5, 'Disabled by Mozilla')], default=1)),
                ('datestatuschanged', models.DateTimeField(auto_now_add=True, null=True)),
                ('is_restart_required', models.BooleanField(default=False)),
                ('strict_compatibility', models.BooleanField(default=False)),
                ('reviewed', models.DateTimeField(blank=True, null=True)),
                ('binary', models.BooleanField(default=False)),
                ('binary_components', models.BooleanField(default=False)),
                ('cert_serial_num', models.TextField(blank=True)),
                ('is_signed', models.BooleanField(default=False)),
                ('is_experiment', models.BooleanField(default=False)),
                ('is_webextension', models.BooleanField(default=False)),
                ('is_mozilla_signed_extension', models.BooleanField(default=False)),
                ('original_status', models.PositiveSmallIntegerField(default=0)),
                ('version', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='files', to='versions.Version')),
            ],
            options={
                'db_table': 'files',
                'get_latest_by': 'created',
                'abstract': False,
                'base_manager_name': 'objects',
            },
            bases=(olympia.amo.models.OnChangeMixin, olympia.amo.models.SaveUpdateMixin, models.Model),
        ),
        migrations.CreateModel(
            name='WebextPermission',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(blank=True, default=django.utils.timezone.now, editable=False)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('permissions', django_extensions.db.fields.json.JSONField(default={})),
                ('file', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='_webext_permissions', to='files.File')),
            ],
            options={
                'db_table': 'webext_permissions',
            },
            bases=(olympia.amo.models.SaveUpdateMixin, models.Model),
        ),
        migrations.CreateModel(
            name='FileValidation',
            fields=[
                ('created', models.DateTimeField(blank=True, default=django.utils.timezone.now, editable=False)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('id', olympia.amo.fields.PositiveAutoField(primary_key=True, serialize=False)),
                ('valid', models.BooleanField(default=False)),
                ('errors', models.IntegerField(default=0)),
                ('warnings', models.IntegerField(default=0)),
                ('notices', models.IntegerField(default=0)),
                ('validation', models.TextField()),
                ('file', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='validation', to='files.File')),
            ],
            options={
                'db_table': 'file_validation',
            },
            bases=(olympia.amo.models.SaveUpdateMixin, models.Model),
        ),
        migrations.CreateModel(
            name='FileUpload',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(blank=True, default=django.utils.timezone.now, editable=False)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('uuid', models.UUIDField(default=uuid.uuid4, editable=False)),
                ('path', models.CharField(default='', max_length=255)),
                ('name', models.CharField(default='', help_text="The user's original filename", max_length=255)),
                ('hash', models.CharField(default='', max_length=255)),
                ('valid', models.BooleanField(default=False)),
                ('validation', models.TextField(null=True)),
                ('automated_signing', models.BooleanField(default=False)),
                ('compat_with_app', models.PositiveIntegerField(choices=[(1, 'Firefox'), (61, 'Firefox for Android')], db_column='compat_with_app_id', null=True)),
                ('version', models.CharField(max_length=255, null=True)),
                ('access_token', models.CharField(max_length=40, null=True)),
                ('addon', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='addons.Addon')),
                ('compat_with_appver', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='uploads_compat_for_appver', to='applications.AppVersion')),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'file_uploads',
                'get_latest_by': 'created',
                'abstract': False,
                'base_manager_name': 'objects',
            },
            bases=(olympia.amo.models.SaveUpdateMixin, models.Model),
        ),
        migrations.AddIndex(
            model_name='fileupload',
            index=models.Index(fields=['compat_with_app'], name='file_uploads_afe99c5e'),
        ),
        migrations.AddConstraint(
            model_name='fileupload',
            constraint=models.UniqueConstraint(fields=('uuid',), name='uuid'),
        ),
        migrations.AddIndex(
            model_name='file',
            index=models.Index(fields=['created', 'version'], name='created_idx'),
        ),
        migrations.AddIndex(
            model_name='file',
            index=models.Index(fields=['binary_components'], name='files_cedd2560'),
        ),
        migrations.AddIndex(
            model_name='file',
            index=models.Index(fields=['datestatuschanged', 'version'], name='statuschanged_idx'),
        ),
        migrations.AddIndex(
            model_name='file',
            index=models.Index(fields=['platform'], name='platform_id'),
        ),
        migrations.AddIndex(
            model_name='file',
            index=models.Index(fields=['status'], name='status'),
        ),
    ]
