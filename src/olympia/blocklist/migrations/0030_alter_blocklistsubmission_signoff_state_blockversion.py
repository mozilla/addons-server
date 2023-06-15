# Generated by Django 4.2.1 on 2023-06-16 09:01

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import olympia.amo.models


class Migration(migrations.Migration):
    dependencies = [
        ('blocklist', '0029_alter_blocklistsubmission_delayed_until_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='blocklistsubmission',
            name='signoff_state',
            field=models.SmallIntegerField(
                choices=[
                    (0, 'Pending Sign-off'),
                    (1, 'Approved'),
                    (2, 'Rejected'),
                    (3, 'Auto Sign-off'),
                    (4, 'Published'),
                ],
                default=0,
            ),
        ),
        migrations.CreateModel(
            name='BlockVersion',
            fields=[
                (
                    'id',
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'created',
                    models.DateTimeField(
                        blank=True, default=django.utils.timezone.now, editable=False
                    ),
                ),
                ('modified', models.DateTimeField(auto_now=True)),
                (
                    'block',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to='blocklist.block',
                    ),
                ),
                (
                    'version',
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        to='versions.version',
                    ),
                ),
            ],
            options={
                'get_latest_by': 'created',
                'abstract': False,
                'base_manager_name': 'objects',
            },
            bases=(olympia.amo.models.SaveUpdateMixin, models.Model),
        ),
    ]
