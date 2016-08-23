from olympia import amo
from olympia.amo.tests import TestCase
from olympia.addons.models import Addon
from olympia.addons.utils import reverse_name_lookup


class TestReverseNameLookup(TestCase):
    fixtures = ('base/addon_3615',)

    def setUp(self):
        super(TestReverseNameLookup, self).setUp()
        self.addon = Addon.objects.get()

    def test_delete_addon(self):
        assert reverse_name_lookup('Delicious Bookmarks', amo.ADDON_EXTENSION)
        self.addon.delete('farewell my sweet amo, it was a good run')
        assert not reverse_name_lookup(
            'Delicious Bookmarks', amo.ADDON_EXTENSION)

    def test_update_addon(self):
        assert reverse_name_lookup('Delicious Bookmarks', amo.ADDON_EXTENSION)
        self.addon.name = 'boo'
        self.addon.save()
        assert not reverse_name_lookup(
            'Delicious Bookmarks', amo.ADDON_EXTENSION, self.addon)
        assert reverse_name_lookup('boo', amo.ADDON_EXTENSION)

    def test_get_strip(self):
        assert reverse_name_lookup(
            'Delicious Bookmarks   ', amo.ADDON_EXTENSION)

    def test_get_case(self):
        assert reverse_name_lookup('delicious bookmarks', amo.ADDON_EXTENSION)
