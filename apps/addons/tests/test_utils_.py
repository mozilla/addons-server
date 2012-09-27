from nose.tools import eq_

from addons.utils import get_featured_ids, get_creatured_ids

import amo.tests


class TestGetFeaturedIds(amo.tests.TestCase):
    fixtures = ['addons/featured', 'bandwagon/featured_collections',
                'base/addon_3615', 'base/collections', 'base/featured',
                'base/users']

    no_locale = (1001, 1003, 2464, 7661, 15679)
    en_us_locale = (3481,)
    all_locales = no_locale + en_us_locale
    no_locale_type_one = (1001, 1003, 2464, 7661)

    def setUp(self):
        super(TestGetFeaturedIds, self).setUp()

    def test_by_app(self):
        eq_(set(get_featured_ids(amo.FIREFOX)),
            set(self.all_locales))

    def test_by_type(self):
        eq_(set(get_featured_ids(amo.FIREFOX, 'xx', 1)),
            set(self.no_locale_type_one))

    def test_by_locale(self):
        eq_(set(get_featured_ids(amo.FIREFOX)),
            set(self.all_locales))
        eq_(set(get_featured_ids(amo.FIREFOX, 'xx')),
            set(self.no_locale))
        eq_(set(get_featured_ids(amo.FIREFOX, 'en-US')),
            set(self.no_locale + self.en_us_locale))

    def test_locale_shuffle(self):
        # Make sure the locale-specific add-ons are at the front.
        ids = get_featured_ids(amo.FIREFOX, 'en-US')
        eq_((ids[0],), self.en_us_locale)


class TestGetCreaturedIds(amo.tests.TestCase):
    fixtures = ['addons/featured', 'bandwagon/featured_collections',
                'base/addon_3615', 'base/collections', 'base/featured',
                'base/users']
    category = 22

    no_locale = (1001,)
    en_us_locale = (3481,)

    def setUp(self):
        super(TestGetCreaturedIds, self).setUp()

    def test_by_category(self):
        eq_(set(get_creatured_ids(self.category, None)),
            set(self.no_locale))

    def test_by_locale(self):
        eq_(set(get_creatured_ids(self.category, 'en-US')),
            set(self.no_locale + self.en_us_locale))

    def test_shuffle(self):
        ids = get_creatured_ids(self.category, 'en-US')
        eq_((ids[0],), self.en_us_locale)
