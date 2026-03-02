from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('scanners', '0073_scannerresult_activity_log'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='scannerresult',
            name='scanners_re_state_2893a0_idx',
        ),
        migrations.RemoveField(
            model_name='scannerresult',
            name='state',
        ),
    ]
