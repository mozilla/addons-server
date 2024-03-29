# Generated by Django 2.2.5 on 2019-09-12 13:35

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import olympia.amo.fields
import olympia.amo.models
import olympia.translations.fields


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('translations', '__first__'),
        ('addons', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Collection',
            fields=[
                ('created', models.DateTimeField(blank=True, default=django.utils.timezone.now, editable=False)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('id', olympia.amo.fields.PositiveAutoField(primary_key=True, serialize=False)),
                ('uuid', models.UUIDField(blank=True, null=True, unique=True)),
                ('nickname', models.CharField(blank=True, max_length=30, null=True, unique=True)),
                ('slug', models.CharField(blank=True, max_length=30, null=True)),
                ('default_locale', models.CharField(db_column='defaultlocale', default='en-US', max_length=10)),
                ('type', models.PositiveIntegerField(choices=[(0, 'Normal'), (1, 'Synchronized'), (2, 'Featured'), (3, 'Generated Recommendations'), (4, 'Favorites'), (5, 'Mobile'), (6, 'Anonymous')], db_column='collection_type', default=0)),
                ('listed', models.BooleanField(default=True, help_text='Collections are either listed or private.')),
                ('application', models.PositiveIntegerField(blank=True, choices=[(1, 'Firefox'), (61, 'Firefox for Android')], db_column='application_id', null=True)),
                ('addon_count', models.PositiveIntegerField(db_column='addonCount', default=0)),
            ],
            options={
                'db_table': 'collections',
                'get_latest_by': 'created',
                'abstract': False,
                'base_manager_name': 'objects',
            },
            bases=(olympia.amo.models.SaveUpdateMixin, models.Model),
        ),
        migrations.CreateModel(
            name='FeaturedCollection',
            fields=[
                ('created', models.DateTimeField(blank=True, default=django.utils.timezone.now, editable=False)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('id', olympia.amo.fields.PositiveAutoField(primary_key=True, serialize=False)),
                ('application', models.PositiveIntegerField(choices=[(1, 'Firefox'), (61, 'Firefox for Android')], db_column='application_id')),
                ('locale', models.CharField(max_length=10, null=True)),
                ('collection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bandwagon.Collection')),
            ],
            options={
                'db_table': 'featured_collections',
            },
            bases=(olympia.amo.models.SaveUpdateMixin, models.Model),
        ),
        migrations.CreateModel(
            name='CollectionAddon',
            fields=[
                ('created', models.DateTimeField(blank=True, default=django.utils.timezone.now, editable=False)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('id', olympia.amo.fields.PositiveAutoField(primary_key=True, serialize=False)),
                ('ordering', models.PositiveIntegerField(default=0, help_text='Add-ons are displayed in ascending order based on this field.')),
                ('addon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='addons.Addon')),
                ('collection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bandwagon.Collection')),
                ('comments', olympia.translations.fields.LinkifiedField(blank=True, db_column='comments', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='CollectionAddon_comments_set+', require_locale=True, short=True, to='translations.LinkifiedTranslation', to_field='id', unique=True)),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'addons_collections',
                'get_latest_by': 'created',
                'abstract': False,
                'base_manager_name': 'objects',
            },
            bases=(olympia.amo.models.SaveUpdateMixin, models.Model),
        ),
        migrations.AddField(
            model_name='collection',
            name='addons',
            field=models.ManyToManyField(related_name='collections', through='bandwagon.CollectionAddon', to='addons.Addon'),
        ),
        migrations.AddField(
            model_name='collection',
            name='author',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='collections', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='collection',
            name='description',
            field=olympia.translations.fields.NoURLsField(blank=True, db_column='description', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='Collection_description_set+', require_locale=False, short=True, to='translations.NoURLsTranslation', to_field='id', unique=True),
        ),
        migrations.AddField(
            model_name='collection',
            name='name',
            field=olympia.translations.fields.TranslatedField(blank=True, db_column='name', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='Collection_name_set+', require_locale=False, short=True, to='translations.Translation', to_field='id', unique=True),
        ),
        migrations.AddIndex(
            model_name='featuredcollection',
            index=models.Index(fields=['application'], name='application_id_idx'),
        ),
        migrations.AddIndex(
            model_name='collectionaddon',
            index=models.Index(fields=['collection', 'created'], name='created_idx'),
        ),
        migrations.AddIndex(
            model_name='collectionaddon',
            index=models.Index(fields=['addon'], name='addon_id'),
        ),
        migrations.AddIndex(
            model_name='collectionaddon',
            index=models.Index(fields=['collection'], name='collection_id'),
        ),
        migrations.AddIndex(
            model_name='collectionaddon',
            index=models.Index(fields=['user'], name='user_id'),
        ),
        migrations.AddConstraint(
            model_name='collectionaddon',
            constraint=models.UniqueConstraint(fields=('addon', 'collection'), name='addon_id_2'),
        ),
        migrations.AddIndex(
            model_name='collection',
            index=models.Index(fields=['application'], name='application_id'),
        ),
        migrations.AddIndex(
            model_name='collection',
            index=models.Index(fields=['created'], name='created_idx'),
        ),
        migrations.AddIndex(
            model_name='collection',
            index=models.Index(fields=['listed'], name='listed'),
        ),
        migrations.AddIndex(
            model_name='collection',
            index=models.Index(fields=['slug'], name='slug_idx'),
        ),
        migrations.AddIndex(
            model_name='collection',
            index=models.Index(fields=['type'], name='type_idx'),
        ),
        migrations.AddConstraint(
            model_name='collection',
            constraint=models.UniqueConstraint(fields=('author', 'slug'), name='author_id'),
        ),
    ]
