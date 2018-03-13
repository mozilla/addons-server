import pytest
from django.forms import ValidationError

from olympia import amo
from olympia.addons.models import Category
from olympia.addons.utils import (
    get_creatured_ids, get_featured_ids, verify_mozilla_trademark)
from olympia.amo.tests import (
    TestCase, addon_factory, collection_factory, user_factory)
from olympia.bandwagon.models import FeaturedCollection
from olympia.constants.categories import CATEGORIES_BY_ID


@pytest.mark.django_db
@pytest.mark.parametrize('name, allowed, email', (
    # Regular name, obviously always allowed
    ('Fancy new Add-on', True, 'foo@bar.com'),
    # We allow the 'for ...' postfix to be used
    ('Fancy new Add-on for Firefox', True, 'foo@bar.com'),
    ('Fancy new Add-on for Mozilla', True, 'foo@bar.com'),
    # But only the postfix
    ('Fancy new Add-on for Firefox Browser', False, 'foo@bar.com'),
    ('For Firefox fancy new add-on', False, 'foo@bar.com'),
    # But users with @mozilla.com or @mozilla.org email addresses
    # are allowed
    ('Firefox makes everything better', False, 'bar@baz.com'),
    ('Firefox makes everything better', True, 'foo@mozilla.com'),
    ('Firefox makes everything better', True, 'foo@mozilla.org'),
    ('Mozilla makes everything better', True, 'foo@mozilla.com'),
    ('Mozilla makes everything better', True, 'foo@mozilla.org'),
    # A few more test-cases...
    ('Firefox add-on for Firefox', False, 'foo@bar.com'),
    ('Firefox add-on for Firefox', True, 'foo@mozilla.com'),
    ('Foobarfor Firefox', False, 'foo@bar.com'),
    ('Better Privacy for Firefox!', True, 'foo@bar.com'),
    ('Firefox awesome for Mozilla', False, 'foo@bar.com'),
    ('Firefox awesome for Mozilla', True, 'foo@mozilla.org'),
))
def test_verify_mozilla_trademark(name, allowed, email):
    user = user_factory(email=email)

    if not allowed:
        with pytest.raises(ValidationError) as exc:
            verify_mozilla_trademark(name, user)
        assert exc.value.message == (
            'Add-on names cannot contain the Mozilla or Firefox trademarks.'
        )
    else:
        verify_mozilla_trademark(name, user)


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
