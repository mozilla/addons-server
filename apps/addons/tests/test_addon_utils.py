import test_utils
from nose.tools import eq_

import amo.tests
from addons.models import Addon
from addons.utils import ReverseNameLookup
from addons import cron


class TestReverseNameLookup(amo.tests.RedisTest, test_utils.TestCase):
    fixtures = ('base/addon_3615',)

    def setUp(self):
        super(TestReverseNameLookup, self).setUp()
        cron.build_reverse_name_lookup()
        self.addon = Addon.objects.get()

    def test_delete_addon(self):
        eq_(ReverseNameLookup.get('Delicious Bookmarks'), 3615)
        self.addon.delete('farewell my sweet amo, it was a good run')
        eq_(ReverseNameLookup.get('Delicious Bookmarks'), None)

    def test_update_addon(self):
        eq_(ReverseNameLookup.get('Delicious Bookmarks'), 3615)
        self.addon.name = 'boo'
        self.addon.save()
        eq_(ReverseNameLookup.get('Delicious Bookmarks'), None)
        eq_(ReverseNameLookup.get('boo'), 3615)

    def test_get_strip(self):
        eq_(ReverseNameLookup.get('Delicious Bookmarks   '), 3615)

    def test_get_case(self):
        eq_(ReverseNameLookup.get('delicious bookmarks'), 3615)
