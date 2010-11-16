import test_utils
from nose.tools import eq_

from redisutils import mock_redis

from addons.models import Addon
from addons.utils import ReverseNameLookup
from addons import cron


class TestReverseNameLookup(test_utils.TestCase):
    fixtures = ('base/addon_3615',)

    def setUp(self):
        mock_redis()
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
