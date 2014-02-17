from nose.tools import eq_

import amo.tests
from addons.models import Addon
from addons.utils import reverse_name_lookup


class TestReverseNameLookup(amo.tests.TestCase):
    fixtures = ('base/addon_3615',)

    def setUp(self):
        super(TestReverseNameLookup, self).setUp()
        self.addon = Addon.objects.get()

    def test_delete_addon(self):
        eq_(reverse_name_lookup('Delicious Bookmarks'), 3615)
        self.addon.delete('farewell my sweet amo, it was a good run')
        eq_(reverse_name_lookup('Delicious Bookmarks'), None)

    def test_update_addon(self):
        eq_(reverse_name_lookup('Delicious Bookmarks'), 3615)
        self.addon.name = 'boo'
        self.addon.save()
        eq_(reverse_name_lookup('Delicious Bookmarks'), None)
        eq_(reverse_name_lookup('boo'), 3615)

    def test_get_strip(self):
        eq_(reverse_name_lookup('Delicious Bookmarks   '), 3615)

    def test_get_case(self):
        eq_(reverse_name_lookup('delicious bookmarks'), 3615)
