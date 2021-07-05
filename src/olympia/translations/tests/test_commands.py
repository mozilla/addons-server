from django.core.management import call_command

from olympia.amo.tests import addon_factory, TestCase
from olympia.bandwagon.models import Collection
from olympia.translations.models import Translation
from olympia.translations.management.commands.process_translations import (
    Command as ProcessTranslationsCommand,
)


class TestTranslationCommands(TestCase):
    def setUp(self):
        self.collection = Collection.objects.create(
            name='foo_collection_name', description='foo_collection_description'
        )
        # Orphaned translation: should not be touched.
        Translation.objects.create(
            id=667, localized_string='foo', localized_string_clean='bar', locale='de'
        )
        # Orphaned translation for the same string in a different locale:
        # should not be touched.
        Translation.objects.create(
            id=667,
            localized_string='foo2',
            localized_string_clean='bar2',
            locale='fr',
        )

        # Translation belonging to a collection name: should not be touched.
        self.collection.name.localized_string_clean = 'bar_collection_name'
        self.collection.name.save()
        # Translation belonging to an add-on: should not be touched.
        addon = addon_factory(name='foo_addon')
        addon.name.localized_string_clean = 'bar_addon'
        addon.name.save()
        # Translation belonging to a collection description that we don't need to bother
        # with (because its localized string clean should already match its localized
        # string): should not be touched.
        extra_collection = Collection.objects.create(
            name='foo_collection_name2', description='foo_collection_description2'
        )
        extra_collection.description.update(modified=self.days_ago(42))

        # The command should fix this one.
        self.collection.description.update(
            localized_string_clean='bar_collection_description',
            modified=self.days_ago(42),
        )
        self.collection.description.reload()

    def test_queryset(self):
        command = ProcessTranslationsCommand()
        qs = command.get_base_queryset({})
        pks = command.get_pks(
            qs,
            command.get_tasks()['reclean_collection_descriptions']['queryset_filters'],
        )
        assert list(pks) == [self.collection.description.pk]

    def test_reclean_collection_descriptions(self):
        call_command('process_translations', task='reclean_collection_descriptions')

        # We forcibly set localized_string_clean to be different than localized_string.
        # Firing the command should have changed it back.
        self.collection.description.reload()
        self.assertCloseToNow(self.collection.description.modified)
        assert (
            self.collection.description.localized_string_clean
            == self.collection.description.localized_string
        )
