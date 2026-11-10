from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('scanners', '0094_alter_scannerwebhookevent_event'),
    ]

    operations = [
        migrations.AlterField(
            model_name='scannerrule',
            name='is_active',
            field=models.BooleanField(
                default=True,
                help_text=(
                    'When unchecked, scanner results will not be linked to this rule '
                    'and its automated actions will not be executed. For webhook '
                    'rules, only uncheck this as a last resort in an emergency.'
                ),
            ),
        ),
    ]
