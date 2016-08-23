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
        match = reverse_name_lookup(
            'Delicious Bookmarks', addon_type=amo.ADDON_EXTENSION)
        assert match.keys() == [3615]

        self.addon.delete('farewell my sweet amo, it was a good run')
        assert reverse_name_lookup(
            'Delicious Bookmarks', addon_type=amo.ADDON_EXTENSION) is None

    def test_update_addon(self):
        match = reverse_name_lookup(
            'Delicious Bookmarks', addon_type=amo.ADDON_EXTENSION)
        assert match.keys() == [3615]

        self.addon.name = 'boo'
        self.addon.save()
        assert reverse_name_lookup(
            'Delicious Bookmarks', addon_type=amo.ADDON_EXTENSION) is None
        match = reverse_name_lookup(
            'boo', addon_type=amo.ADDON_EXTENSION)
        assert match.keys() == [3615]

    def test_get_strip(self):
        match = reverse_name_lookup(
            'Delicious Bookmarks   ', addon_type=amo.ADDON_EXTENSION)
        assert match.keys() == [3615]

    def test_get_case(self):
        match = reverse_name_lookup(
            'delicious bookmarks', addon_type=amo.ADDON_EXTENSION)
        assert match.keys() == [3615]
