# -*- coding: utf-8 -*-
from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase
from olympia.bandwagon.models import (
    Collection,
    CollectionAddon,
    FeaturedCollection,
)
from olympia.constants.applications import APPS
from olympia.landfill.collection import generate_collection


class CollectionsTests(TestCase):
    def setUp(self):
        super(CollectionsTests, self).setUp()
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

    def test_collections_themes_generation(self):
        generate_collection(self.addon)
        assert Collection.objects.all().count() == 1
        assert CollectionAddon.objects.last().addon == self.addon
        assert FeaturedCollection.objects.all().count() == 0

    def test_collections_themes_translations(self):
        generate_collection(self.addon)
        with self.activate(locale='es'):
            collection_name = unicode(Collection.objects.last().name)
            assert collection_name.startswith(u'(español) ')

    def test_collections_addons_generation(self):
        generate_collection(self.addon, APPS['android'])
        assert Collection.objects.all().count() == 1
        assert CollectionAddon.objects.last().addon == self.addon
        assert FeaturedCollection.objects.last().application == (
            APPS['android'].id
        )

    def test_collections_addons_translations(self):
        generate_collection(self.addon, APPS['android'])
        with self.activate(locale='es'):
            collection_name = unicode(Collection.objects.last().name)
            assert collection_name.startswith(u'(español) ')
