import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reviewers', '0049_autoapprovalsummary_is_waiting_on_scanners'),
        ('versions', '0052_delete_enable_source_builder_waffle_switch'),
    ]

    operations = [
        migrations.CreateModel(
            name='ZendeskTicket',
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
                ('ticket_id', models.CharField(max_length=255)),
                (
                    'version',
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='zendesk_ticket',
                        to='versions.version',
                    ),
                ),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
