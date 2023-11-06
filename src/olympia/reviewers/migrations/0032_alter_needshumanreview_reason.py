# Generated by Django 4.2.7 on 2023-11-06 16:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reviewers', '0031_reviewactionreason_canned_block_reason'),
    ]

    operations = [
        migrations.AlterField(
            model_name='needshumanreview',
            name='reason',
            field=models.SmallIntegerField(choices=[(0, 'Unknown'), (1, 'Hit scanner rule'), (2, 'Belongs to a promoted group'), (3, 'Over growth threshold for usage tier'), (4, 'Previous version in channel had needs human review set'), (5, 'Sources provided while pending rejection'), (6, 'Developer replied'), (7, 'Manually set as needing human review by a reviewer'), (8, 'Auto-approved but still had an approval delay set in the past'), (9, 'Over abuse reports threshold for usage tier'), (10, 'Escalated for an abuse report, via cinder'), (11, 'Reported for abuse within the add-on'), (12, 'Appeal about a decision on abuse reported within the add-on')], default=0, editable=False),
        ),
    ]
