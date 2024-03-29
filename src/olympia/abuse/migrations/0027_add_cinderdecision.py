# Generated by Django 4.2.10 on 2024-03-11 17:03

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import olympia.amo.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('bandwagon', '0008_alter_collection_options_alter_collection_managers_and_more'),
        ('addons', '0049_clear_bad_url_data'),
        ('ratings', '0011_remove_rating_one_review_per_user_and_more'),
        ('abuse', '0026_add_cinderjob_decision_cinder_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cinderjob',
            name='decision_action',
            field=models.PositiveSmallIntegerField(choices=[(1, 'User ban'), (2, 'Add-on disable'), (3, 'Escalate add-on to reviewers'), (5, 'Rating delete'), (6, 'Collection delete'), (7, 'Approved (no action)'), (8, 'Add-on version reject')], null=True),
        ),
        migrations.AlterField(
            model_name='cinderjob',
            name='decision_notes',
            field=models.TextField(blank=True, max_length=1000, null=True),
        ),
        migrations.RemoveField(
            model_name='cinderjob',
            name='decision_id',
        ),
        migrations.CreateModel(
            name='CinderDecision',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(blank=True, default=django.utils.timezone.now, editable=False)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('action', models.PositiveSmallIntegerField(choices=[(1, 'User ban'), (2, 'Add-on disable'), (3, 'Escalate add-on to reviewers'), (5, 'Rating delete'), (6, 'Collection delete'), (7, 'Approved (no action)'), (8, 'Add-on version reject'), (9, 'Add-on version delayed reject warning')])),
                ('cinder_id', models.CharField(default=None, max_length=36, null=True, unique=True)),
                ('notes', models.TextField(blank=True, max_length=1000)),
                ('date', models.DateTimeField(default=django.utils.timezone.now)),
                ('addon', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='addons.addon')),
                ('appeal_job', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='appealed_decisions', to='abuse.cinderjob')),
                ('collection', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='bandwagon.collection')),
                ('policies', models.ManyToManyField(to='abuse.cinderpolicy')),
                ('rating', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='ratings.rating')),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            bases=(olympia.amo.models.SaveUpdateMixin, models.Model),
        ),
        migrations.AddField(
            model_name='cinderjob',
            name='decision',
            field=models.OneToOneField(null=True, on_delete=django.db.models.deletion.SET_NULL, to='abuse.cinderdecision'),
        ),
        migrations.AddConstraint(
            model_name='cinderdecision',
            constraint=models.CheckConstraint(check=models.Q(models.Q(('addon__isnull', False), ('collection__isnull', True), ('rating__isnull', True), ('user__isnull', True)), models.Q(('addon__isnull', True), ('collection__isnull', True), ('rating__isnull', True), ('user__isnull', False)), models.Q(('addon__isnull', True), ('collection__isnull', True), ('rating__isnull', False), ('user__isnull', True)), models.Q(('addon__isnull', True), ('collection__isnull', False), ('rating__isnull', True), ('user__isnull', True)), _connector='OR'), name='just_one_of_addon_user_rating_collection_must_be_set'),
        ),
    ]
