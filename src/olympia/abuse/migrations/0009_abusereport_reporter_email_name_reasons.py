# Generated by Django 4.2.5 on 2023-10-03 08:54

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('abuse', '0008_alter_abusereport_report_entry_point'),
    ]

    operations = [
        migrations.AddField(
            model_name='abusereport',
            name='reporter_email',
            field=models.CharField(default=None, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='abusereport',
            name='reporter_name',
            field=models.CharField(default=None, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='abusereport',
            name='reason',
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[
                    (None, 'None'),
                    (1, 'Damages computer and/or data'),
                    (2, 'Creates spam or advertising'),
                    (
                        3,
                        'Changes search / homepage / new tab page without informing user',
                    ),
                    (5, 'Doesn’t work, breaks websites, or slows Firefox down'),
                    (6, 'Hateful, violent, or illegal content'),
                    (7, 'Pretends to be something it’s not'),
                    (9, "Wasn't wanted / impossible to get rid of"),
                    (11, 'DSA: Contains hate speech'),
                    (12, 'DSA: Contains child sexual abuse material'),
                    (
                        20,
                        'Feedback: Doesn’t work, breaks websites, or slows Firefox down',
                    ),
                    (21, "Feedback: Wasn't wanted or can't be uninstalled"),
                    (127, 'Other'),
                ],
                default=None,
                null=True,
            ),
        ),
    ]
