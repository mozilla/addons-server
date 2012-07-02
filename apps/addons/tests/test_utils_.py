import mock
from nose.tools import eq_

from addons.utils import get_featured_ids, get_creatured_ids

from waffle import Switch
import amo.tests


class TestGetFeaturedIds(amo.tests.TestCase):
    fixtures = ['addons/featured', 'bandwagon/featured_collections',
                'base/addon_3615', 'base/collections', 'base/featured']

    def setUp(self):
        super(TestGetFeaturedIds, self).setUp()
        Switch.objects.create(name='no-redis', active=True)

    def test_by_app(self):
        eq_(set(get_featured_ids(amo.FIREFOX)),
            set([1001, 1003, 2464, 3481, 7661, 15679]))
        eq_(set(get_featured_ids(amo.FIREFOX, 'xx')),
            set([1001, 1003, 2464, 7661, 15679]))

    def test_by_type(self):
        eq_(set(get_featured_ids(amo.FIREFOX, 'xx', 1)),
            set([1001, 1003, 2464, 7661]))

    def test_by_locale(self):
        eq_(sorted(get_featured_ids(amo.FIREFOX, 'en-US')),
            [1001, 1003, 2464, 3481, 7661, 15679])

    def test_locale_shuffle(self):
        # Make sure the locale-specific add-ons are at the front.
        ids = get_featured_ids(amo.FIREFOX, 'en-US')
        eq_(ids[0], 3481)


class TestGetCreaturedIds(amo.tests.TestCase):
    fixtures = ['addons/featured', 'bandwagon/featured_collections',
                'base/addon_3615', 'base/collections', 'base/featured']
    category = 22

    def setUp(self):
        super(TestGetCreaturedIds, self).setUp()
        Switch.objects.create(name='no-redis', active=True)

    def test_by_category(self):
        eq_(set(get_creatured_ids(self.category, None)), set([1001]))

    def test_by_locale(self):
        eq_(set(get_creatured_ids(self.category, 'en-US')), set([1001, 3481]))

    def test_shuffle(self):
        ids = get_creatured_ids(self.category, 'en-US')
        eq_(ids[0], 3481)
