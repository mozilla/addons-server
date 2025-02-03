from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase
from olympia.bandwagon.models import Collection, CollectionAddon
from olympia.constants.applications import APPS
from olympia.landfill.collection import generate_collection


class CollectionsTests(TestCase):
    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

    def test_collections_themes_generation(self):
        generate_collection(self.addon)
        assert Collection.objects.all().count() == 1
        assert CollectionAddon.objects.last().addon == self.addon

    def test_collections_themes_translations(self):
        generate_collection(self.addon)
        with self.activate(locale='es-ES'):
            collection_name = str(Collection.objects.last().name)
            assert collection_name.startswith('(español) ')

    def test_collections_addons_generation(self):
        generate_collection(self.addon, APPS['android'])
        assert Collection.objects.all().count() == 1
        assert CollectionAddon.objects.last().addon == self.addon

    def test_collections_addons_translations(self):
        generate_collection(self.addon, APPS['android'])
        with self.activate(locale='es-ES'):
            collection_name = str(Collection.objects.last().name)
            assert collection_name.startswith('(español) ')
