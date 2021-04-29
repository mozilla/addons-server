import datetime
import os
from unittest import mock

from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from olympia import amo
from olympia.addons.models import AddonCategory
from olympia.amo.sitemap import (
    AddonSitemap,
    AMOSitemap,
    build_sitemap,
    CategoriesSitemap,
    CollectionSitemap,
    get_sitemap_path,
    get_sitemap_section_pages,
    sitemaps,
)
from olympia.amo.tests import (
    addon_factory,
    collection_factory,
    license_factory,
    user_factory,
)
from olympia.constants.categories import CATEGORIES
from olympia.ratings.models import Rating

from .test_views import TEST_SITEMAPS_DIR


def rating_factory(addon):
    return Rating.objects.create(
        addon=addon,
        version=addon.current_version,
        rating=2,
        body='text',
        user=user_factory(),
    )


def test_addon_sitemap():
    it = AddonSitemap.item_tuple
    addon_a = addon_factory(
        slug='addon-a',
        privacy_policy='privacy!',
        eula='eula!',
        version_kw={'license': license_factory()},
    )
    # addon_factory generates licenses by default, but always with a builtin >0
    addon_b = addon_factory(slug='addon-b')
    addon_b.update(last_updated=datetime.datetime(2020, 1, 1, 1, 1, 1))
    addon_c = addon_factory(
        slug='addon-c',
        eula='only eula',
        version_kw={'license': license_factory(builtin=1)},
    )
    addon_d = addon_factory(slug='addon-d', privacy_policy='only privacy')
    addon_factory(status=amo.STATUS_NOMINATED)  # shouldn't show up
    sitemap = AddonSitemap()
    expected = [
        it(addon_d.last_updated, addon_d.slug, 'detail', 1),
        it(addon_c.last_updated, addon_c.slug, 'detail', 1),
        it(addon_a.last_updated, addon_a.slug, 'detail', 1),
        it(addon_b.last_updated, addon_b.slug, 'detail', 1),
        it(addon_d.last_updated, addon_d.slug, 'privacy', 1),
        it(addon_a.last_updated, addon_a.slug, 'privacy', 1),
        it(addon_c.last_updated, addon_c.slug, 'eula', 1),
        it(addon_a.last_updated, addon_a.slug, 'eula', 1),
        it(addon_a.last_updated, addon_a.slug, 'license', 1),
        it(addon_d.last_updated, addon_d.slug, 'ratings.list', 1),
        it(addon_c.last_updated, addon_c.slug, 'ratings.list', 1),
        it(addon_a.last_updated, addon_a.slug, 'ratings.list', 1),
        it(addon_b.last_updated, addon_b.slug, 'ratings.list', 1),
    ]
    items = list(sitemap.items())
    assert items == expected
    for item in sitemap.items():
        assert sitemap.location(item) == reverse(
            'addons.' + item.urlname, args=[item.slug]
        )
        assert '/en-US/firefox/' in sitemap.location(item)
        assert sitemap.lastmod(item) == item.last_updated

    # add some ratings to test the rating page pagination
    rating_factory(addon_c)
    rating_factory(addon_c)
    rating_factory(addon_c)
    rating_factory(addon_a)
    rating_factory(addon_a)  # only 2 for addon_a
    patched_drf_setting = dict(settings.REST_FRAMEWORK)
    patched_drf_setting['PAGE_SIZE'] = 2

    with override_settings(REST_FRAMEWORK=patched_drf_setting):
        items_with_ratings = list(sitemap.items())
    # only one extra url, for a second ratings page, because PAGE_SIZE = 2
    extra_rating = it(addon_c.last_updated, addon_c.slug, 'ratings.list', 2)
    assert extra_rating in items_with_ratings
    assert set(items_with_ratings) - set(expected) == {extra_rating}
    item = items_with_ratings[-3]
    assert sitemap.location(item).endswith('/reviews/?page=2')
    assert sitemap.lastmod(item) == item.last_updated


def test_amo_sitemap():
    sitemap = AMOSitemap()
    for item in sitemap.items():
        assert sitemap.location(item) == reverse(item)


def test_categories_sitemap():
    sitemap = CategoriesSitemap()
    # without any addons we should still generate a url for each category
    empty_cats = list(sitemap.items())
    assert empty_cats == [
        *(
            (category, 1)
            for category in CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION].values()
        ),
        *(
            (category, 1)
            for category in CATEGORIES[amo.FIREFOX.id][amo.ADDON_STATICTHEME].values()
        ),
    ]
    # add some addons and check we generate extra pages when frontend would paginate
    bookmarks_category = CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['bookmarks']
    shopping_category = CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['shopping']
    AddonCategory.objects.create(
        addon=addon_factory(category=bookmarks_category), category=shopping_category
    )
    AddonCategory.objects.create(
        addon=addon_factory(category=shopping_category), category=bookmarks_category
    )
    addon_factory(category=bookmarks_category)
    addon_factory(category=shopping_category, status=amo.STATUS_NOMINATED)
    addon_factory(
        category=shopping_category, version_kw={'application': amo.ANDROID.id}
    )
    # should be 4 addons in shopping (one not public, one not compatible with Firefox,
    # so 2 public), and 3 in bookmarks

    patched_drf_setting = dict(settings.REST_FRAMEWORK)
    patched_drf_setting['PAGE_SIZE'] = 2
    with override_settings(REST_FRAMEWORK=patched_drf_setting):
        cats_with_addons = list(sitemap.items())
    # only one extra url, for a second bookmarks category page, because PAGE_SIZE = 2
    extra = (bookmarks_category, 2)
    assert extra in cats_with_addons
    assert set(cats_with_addons) - set(empty_cats) == {extra}


def test_collection_sitemap(mozilla_user):
    collection_a = collection_factory(
        author=mozilla_user, modified=datetime.datetime(2020, 1, 1, 1, 1, 1)
    )
    collection_b = collection_factory(
        author=mozilla_user, modified=datetime.datetime(2020, 2, 2, 2, 2, 2)
    )

    collection_factory(author=user_factory())  # not mozilla user
    sitemap = CollectionSitemap()
    assert list(sitemap.items()) == [
        (collection_b.modified, collection_b.slug, mozilla_user.id),
        (collection_a.modified, collection_a.slug, mozilla_user.id),
    ]
    for item in sitemap.items():
        assert sitemap.location(item) == reverse(
            'collections.detail', args=[mozilla_user.id, item.slug]
        )
        assert '/en-US/firefox/' in sitemap.location(item)
        assert sitemap.lastmod(item) == item.modified


def test_get_sitemap_section_pages():
    addon_factory()
    addon_factory()
    addon_factory()
    assert list(sitemaps.keys()) == ['amo', 'addons', 'categories', 'collections']

    pages = get_sitemap_section_pages()
    assert pages == [
        ('amo', 1),
        ('addons', 1),
        ('categories', 1),
        ('collections', 1),
    ]
    with mock.patch.object(AddonSitemap, 'limit', 3):
        pages = get_sitemap_section_pages()
        assert pages == [
            ('amo', 1),
            ('addons', 1),
            ('addons', 2),
            ('categories', 1),
            ('collections', 1),
        ]


def test_build_sitemap():
    # test the index sitemap build first
    with mock.patch('olympia.amo.sitemap.get_sitemap_section_pages') as pages_mock:
        pages_mock.return_value = [
            ('amo', 1),
            ('addons', 1),
            ('addons', 2),
        ]
        built = build_sitemap()

        with open(os.path.join(TEST_SITEMAPS_DIR, 'sitemap.xml')) as sitemap:
            assert built == sitemap.read()

    # then a section build
    def items_mock(self):
        return [
            AddonSitemap.item_tuple(
                datetime.datetime(2020, 10, 2, 0, 0, 0), 'delicious-pierogi', 'detail'
            ),
            AddonSitemap.item_tuple(
                datetime.datetime(2020, 10, 1, 0, 0, 0), 'swanky-curry', 'detail'
            ),
            AddonSitemap.item_tuple(
                datetime.datetime(2020, 9, 30, 0, 0, 0), 'spicy-pierogi', 'detail'
            ),
        ]

    with mock.patch.object(AddonSitemap, 'items', items_mock):
        built = build_sitemap('addons')

        with open(os.path.join(TEST_SITEMAPS_DIR, 'sitemap-addons-2.xml')) as sitemap:
            assert built == sitemap.read()


def test_get_sitemap_path():
    path = settings.SITEMAP_STORAGE_PATH
    assert get_sitemap_path() == f'{path}/sitemap.xml'
    assert get_sitemap_path('foo') == f'{path}/sitemap-foo.xml'
    assert get_sitemap_path('foo', 1) == f'{path}/sitemap-foo.xml'
    assert get_sitemap_path('foo', 2) == f'{path}/sitemap-foo-2.xml'
