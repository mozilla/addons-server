from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('scanners', '0095_alter_scannerrule_is_active'),
    ]

    operations = [
        migrations.AlterField(
            model_name='scannerqueryrule',
            name='description',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Human readable description for the scanner rule.',
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name='scannerqueryrule',
            name='pretty_name',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Human-readable name for the scanner rule.',
                max_length=255,
                verbose_name='Human-readable name',
            ),
        ),
        migrations.AlterField(
            model_name='scannerrule',
            name='action',
            field=models.PositiveSmallIntegerField(
                choices=[
                    (1, 'No action'),
                    (20, 'Flag for human review'),
                    (100, 'Delay auto-approval'),
                    (200, 'Delay auto-approval indefinitely'),
                    (300, 'Delay auto-approval indefinitely and add restrictions'),
                    (
                        400,
                        'Delay auto-approval indefinitely and add restrictions to future approvals',
                    ),
                    (500, 'Force-disable and block'),
                ],
                default=1,
                help_text='Workflow action to execute.',
                verbose_name='Workflow action',
            ),
        ),
        migrations.AlterField(
            model_name='scannerrule',
            name='description',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Human readable description for the scanner rule.',
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name='scannerrule',
            name='exclude_promoted_addons',
            field=models.BooleanField(
                default=False,
                help_text='When checked, the automated actions of this rule will not be executed for add-ons that are in a promoted group.',
            ),
        ),
        migrations.AlterField(
            model_name='scannerrule',
            name='pretty_name',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Human-readable name for the scanner rule.',
                max_length=255,
                verbose_name='Human-readable name',
            ),
        ),
    ]
