from olympia import amo
from olympia.addons.models import Category
from olympia.addons.utils import get_creatured_ids, get_featured_ids
from olympia.amo.tests import TestCase, addon_factory, collection_factory
from olympia.bandwagon.models import FeaturedCollection
from olympia.constants.categories import CATEGORIES_BY_ID


class TestGetFeaturedIds(TestCase):
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
        assert set(get_featured_ids(amo.FIREFOX)) == (
            set(self.all_locales))

    def test_by_type(self):
        assert set(get_featured_ids(amo.FIREFOX, 'xx', 1)) == (
            set(self.no_locale_type_one))

    def test_by_locale(self):
        assert set(get_featured_ids(amo.FIREFOX)) == (
            set(self.all_locales))
        assert set(get_featured_ids(amo.FIREFOX, 'xx')) == (
            set(self.no_locale))
        assert set(get_featured_ids(amo.FIREFOX, 'en-US')) == (
            set(self.no_locale + self.en_us_locale))

    def test_locale_shuffle(self):
        # Make sure the locale-specific add-ons are at the front.
        ids = get_featured_ids(amo.FIREFOX, 'en-US')
        assert (ids[0],) == self.en_us_locale


class TestGetCreaturedIds(TestCase):
    fixtures = ['addons/featured', 'bandwagon/featured_collections',
                'base/addon_3615', 'base/collections', 'base/featured',
                'base/users']
    category_id = 22

    no_locale = (1001,)
    en_us_locale = (3481,)

    def setUp(self):
        super(TestGetCreaturedIds, self).setUp()

    def test_by_category_static(self):
        category = CATEGORIES_BY_ID[self.category_id]
        assert set(get_creatured_ids(category, None)) == (
            set(self.no_locale))

    def test_by_category_dynamic(self):
        category = Category.objects.get(pk=self.category_id)
        assert set(get_creatured_ids(category, None)) == (
            set(self.no_locale))

    def test_by_category_id(self):
        assert set(get_creatured_ids(self.category_id, None)) == (
            set(self.no_locale))

    def test_by_category_app(self):
        # Add an addon to the same category, but in a featured collection
        # for a different app: it should not be returned.
        extra_addon = addon_factory(
            category=Category.objects.get(pk=self.category_id))
        collection = collection_factory()
        collection.add_addon(extra_addon)
        FeaturedCollection.objects.create(
            application=amo.THUNDERBIRD.id, collection=collection)

        assert set(get_creatured_ids(self.category_id, None)) == (
            set(self.no_locale))

    def test_by_locale(self):
        assert set(get_creatured_ids(self.category_id, 'en-US')) == (
            set(self.no_locale + self.en_us_locale))

    def test_by_category_app_and_locale(self):
        # Add an addon to the same category and locale, but in a featured
        # collection for a different app: it should not be returned.
        extra_addon = addon_factory(
            category=Category.objects.get(pk=self.category_id))
        collection = collection_factory()
        collection.add_addon(extra_addon)
        FeaturedCollection.objects.create(
            application=amo.THUNDERBIRD.id, collection=collection,
            locale='en-US')

        assert set(get_creatured_ids(self.category_id, 'en-US')) == (
            set(self.no_locale + self.en_us_locale))

    def test_shuffle(self):
        ids = get_creatured_ids(self.category_id, 'en-US')
        assert (ids[0],) == self.en_us_locale
