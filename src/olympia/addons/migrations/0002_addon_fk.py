from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('addons', '0001_initial'),
        ('versions', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='addon',
            name='_current_version',
            field=models.ForeignKey(
                db_column='current_version', null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+', to='versions.Version')),
        migrations.AddIndex(
            model_name='addon',
            index=models.Index(fields=['_current_version'], name='current_version'),
        ),
        migrations.AddIndex(
            model_name='addon',
            index=models.Index(fields=['type', 'status', 'disabled_by_user', '_current_version'], name='visible_idx'),
        ),
    ]
