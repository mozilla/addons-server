import mock
import test_utils
from nose.tools import eq_

from addons.utils import FeaturedManager, CreaturedManager

import amo.tests


class TestFeaturedManager(test_utils.TestCase):

    def setUp(self):
        patcher = mock.patch('addons.utils.FeaturedManager.get_objects')
        self.objects_mock = patcher.start()
        self.addCleanup(patcher.stop)

        # Fake the objects.values() call.
        self.fields = ['addon', 'addon__type', 'locale', 'application']
        self.values = [
            (1, 1, None, 1),
            (2, 1, None, 1),
            (3, 9, None, 1),     # A different type.
            (4, 1, 'ja', 1),     # Restricted locale.
            (5, 1, 'ja', 1),
            (5, 1, 'en-US', 1),  # Same add-on, different locale.
            (6, 1, None, 18),    # Different app.
        ]
        self.objects_mock.return_value = [dict(zip(self.fields, v))
                                          for v in self.values]
        self.fm = FeaturedManager
        self.fm.build()

    def test_build(self):
        eq_(self.fm.redis().smembers(self.fm.by_id), set([1, 2, 3, 4, 5, 6]))

    def test_by_app(self):
        eq_(set(self.fm.featured_ids(amo.FIREFOX, 'xx')), set([1, 2, 3]))

    def test_by_type(self):
        eq_(set(self.fm.featured_ids(amo.FIREFOX, 'xx', 1)), set([1, 2]))

    def test_by_locale(self):
        eq_(sorted(self.fm.featured_ids(amo.FIREFOX, 'ja')), [1, 2, 3, 4, 5])
        eq_(sorted(self.fm.featured_ids(amo.FIREFOX, 'en-US')), [1, 2, 3, 5])

    def test_locale_shuffle(self):
        # Make sure the locale-specific add-ons are at the front.
        ids = self.fm.featured_ids(amo.FIREFOX, 'ja')
        eq_(set(ids[:2]), set([4, 5]))

    def test_reset(self):
        # Drop the first one to make sure we reset the list properly.
        self.values = self.values[1:]
        self.objects_mock.return_value = [dict(zip(self.fields, v))
                                          for v in self.values]
        self.fm.build()
        eq_(set(self.fm.featured_ids(amo.FIREFOX, 'xx')), set([2, 3]))


class TestCreaturedManager(test_utils.TestCase):

    def setUp(self):
        patcher = mock.patch('addons.utils.CreaturedManager.get_objects')
        self.objects_mock = patcher.start()
        self.addCleanup(patcher.stop)

        self.category = mock.Mock()
        self.category.id = 1

        self.fields = ['category', 'addon', 'feature_locales']
        self.values = [
            (1, 1, None),     # No locales.
            (1, 2, ''),       # Make sure empty string is ok.
            (2, 3, None),     # Something from a different category.
            (1, 4, 'ja'),     # Check locales with no comma.
            (1, 5, 'ja,en'),  # Locales with a comma.
        ]
        self.objects_mock.return_value = [dict(zip(self.fields, v))
                                          for v in self.values]
        self.cm = CreaturedManager
        self.cm.build()

    def test_by_category(self):
        eq_(set(self.cm.creatured_ids(self.category, 'xx')), set([1, 2]))

    def test_by_locale(self):
        eq_(set(self.cm.creatured_ids(self.category, 'ja')), set([1, 2, 4, 5]))

    def test_shuffle(self):
        ids = self.cm.creatured_ids(self.category, 'ja')
        eq_(set(ids[:2]), set([4, 5]))

    def test_reset(self):
        self.values = self.values[1:]
        self.objects_mock.return_value = [dict(zip(self.fields, v))
                                          for v in self.values]
        self.cm.build()
        eq_(set(self.cm.creatured_ids(self.category, 'xx')), set([2]))
