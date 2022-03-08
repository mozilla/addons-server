import os
from unittest import mock
from datetime import datetime

from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from olympia import amo
from olympia.addons.models import AddonCategory
from olympia.amo.sitemap import (
    AccountSitemap,
    AddonSitemap,
    AMOSitemap,
    CategoriesSitemap,
    CollectionSitemap,
    get_sitemap_path,
    get_sitemap_section_pages,
    get_sitemaps,
    render_index_xml,
    TagPagesSitemap,
)
from olympia.amo.reverse import override_url_prefix
from olympia.amo.tests import (
    addon_factory,
    collection_factory,
    TestCase,
    user_factory,
    version_factory,
)
from olympia.constants.categories import CATEGORIES
from olympia.constants.promoted import RECOMMENDED
from olympia.ratings.models import Rating
from olympia.tags.models import Tag

from .test_views import TEST_SITEMAPS_DIR


def rating_factory(addon):
    return Rating.objects.create(
        addon=addon,
        version=addon.current_version,
        rating=2,
        body='text',
        user=user_factory(),
    )


class TestAddonSitemap(TestCase):
    def setUp(self):
        it = AddonSitemap.item_tuple
        self.addon_a = addon_a = addon_factory(slug='addon-a')
        self.addon_b = addon_b = addon_factory(slug='addon-b')
        addon_b.update(last_updated=datetime(2020, 1, 1, 1, 1, 1))
        self.addon_c = addon_c = addon_factory(slug='addon-c')
        addon_factory(status=amo.STATUS_NOMINATED)  # shouldn't show up
        self.android_addon = addon_factory(
            version_kw={'application': amo.ANDROID.id}
        )  # shouldn't show up in expected
        self.make_addon_promoted(self.android_addon, RECOMMENDED, approve_version=True)
        self.expected = [
            it(addon_c.last_updated, reverse('addons.detail', args=[addon_c.slug]), 1),
            it(addon_a.last_updated, reverse('addons.detail', args=[addon_a.slug]), 1),
            it(addon_b.last_updated, reverse('addons.detail', args=[addon_b.slug]), 1),
            it(
                addon_c.last_updated,
                reverse('addons.ratings.list', args=[addon_c.slug]),
                1,
            ),
            it(
                addon_a.last_updated,
                reverse('addons.ratings.list', args=[addon_a.slug]),
                1,
            ),
            it(
                addon_b.last_updated,
                reverse('addons.ratings.list', args=[addon_b.slug]),
                1,
            ),
        ]

    def test_basic(self):
        sitemap = AddonSitemap()
        items = list(sitemap.items())
        assert items == self.expected
        for item in sitemap.items():
            assert sitemap.location(item) == item.url
            assert '/en-US/firefox/' in sitemap.location(item)
            assert sitemap.lastmod(item) == item.last_updated

    def test_rating_pagination(self):
        # add some ratings to test the rating page pagination
        rating_factory(self.addon_c)
        rating_factory(self.addon_c)
        rating_factory(self.addon_c)
        rating_factory(self.addon_a)
        rating_factory(self.addon_a)  # only 2 for addon_a
        patched_drf_setting = dict(settings.REST_FRAMEWORK)
        patched_drf_setting['PAGE_SIZE'] = 2

        sitemap = AddonSitemap()
        with override_settings(REST_FRAMEWORK=patched_drf_setting):
            items_with_ratings = list(sitemap.items())
        # only one extra url, for a second ratings page, because PAGE_SIZE = 2
        extra_rating = AddonSitemap.item_tuple(
            self.addon_c.last_updated,
            reverse('addons.ratings.list', args=[self.addon_c.slug]),
            2,
        )
        assert extra_rating in items_with_ratings
        assert set(items_with_ratings) - set(self.expected) == {extra_rating}
        item = items_with_ratings[-3]
        assert sitemap.location(item).endswith('/reviews/?page=2')
        assert sitemap.lastmod(item) == item.last_updated

    def test_android(self):
        it = AddonSitemap.item_tuple
        android_addon = self.android_addon
        with override_url_prefix(app_name='android'):
            assert list(AddonSitemap().items()) == [
                it(
                    android_addon.last_updated,
                    reverse('addons.detail', args=[android_addon.slug]),
                    1,
                ),
                it(
                    android_addon.last_updated,
                    reverse('addons.ratings.list', args=[android_addon.slug]),
                    1,
                ),
            ]
            # make some of the Firefox add-ons be Android compatible
            version_factory(addon=self.addon_a, application=amo.ANDROID.id)
            self.make_addon_promoted(self.addon_a, RECOMMENDED, approve_version=True)
            self.addon_a.reload()
            version_factory(addon=self.addon_b, application=amo.ANDROID.id)
            # don't make b recommended - should be ignored even though it's compatible
            assert list(AddonSitemap().items()) == [
                it(
                    self.addon_a.last_updated,
                    reverse('addons.detail', args=[self.addon_a.slug]),
                    1,
                ),
                it(
                    android_addon.last_updated,
                    reverse('addons.detail', args=[android_addon.slug]),
                    1,
                ),
                it(
                    self.addon_a.last_updated,
                    reverse('addons.ratings.list', args=[self.addon_a.slug]),
                    1,
                ),
                it(
                    android_addon.last_updated,
                    reverse('addons.ratings.list', args=[android_addon.slug]),
                    1,
                ),
            ]


def test_amo_sitemap():
    sitemap = AMOSitemap()
    for item in sitemap.items():
        urlname, app = item
        assert sitemap.location(item).endswith(reverse(urlname, add_prefix=False))
        if app:
            assert sitemap.location(item).endswith(
                f'/{app.short}{reverse(urlname, add_prefix=False)}'
            )


def test_categories_sitemap():
    # without any addons we should still generate a url for each category
    empty_cats = list(CategoriesSitemap().items())
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
    addon_factory(category=bookmarks_category)
    addon_factory(category=bookmarks_category)
    addon_factory(category=shopping_category, status=amo.STATUS_NOMINATED)
    addon_factory(
        category=shopping_category, version_kw={'application': amo.ANDROID.id}
    )
    # should be 4 addons in shopping (one not public, one not compatible with Firefox,
    # so 2 public), and 5 in bookmarks

    patched_drf_setting = dict(settings.REST_FRAMEWORK)
    patched_drf_setting['PAGE_SIZE'] = 2
    with override_settings(REST_FRAMEWORK=patched_drf_setting):
        cats_with_addons = list(CategoriesSitemap().items())
    # two extra urls, for second+third bookmarks category pages, because PAGE_SIZE = 2
    extra_2 = (bookmarks_category, 2)
    extra_3 = (bookmarks_category, 3)
    assert extra_2 in cats_with_addons
    assert extra_3 in cats_with_addons
    assert set(cats_with_addons) - set(empty_cats) == {extra_2, extra_3}

    # now limit the number of items that would be paginated over so bookmarks count == 4
    with override_settings(REST_FRAMEWORK=patched_drf_setting, ES_MAX_RESULT_WINDOW=4):
        cats_limited = list(CategoriesSitemap().items())
    assert extra_3 not in cats_limited
    assert set(cats_limited) - set(empty_cats) == {extra_2}


def test_collection_sitemap(mozilla_user):
    collection_a = collection_factory(
        author=mozilla_user, modified=datetime(2020, 1, 1, 1, 1, 1)
    )
    collection_b = collection_factory(
        author=mozilla_user, modified=datetime(2020, 2, 2, 2, 2, 2)
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


class TestAccountSitemap(TestCase):
    def test_basic(self):
        user_with_themes = user_factory()
        user_with_extensions = user_factory()
        user_with_both = user_factory()
        user_factory(is_public=True)  # marked as public, but no addons.
        extension = addon_factory(users=(user_with_extensions, user_with_both))
        theme = addon_factory(
            type=amo.ADDON_STATICTHEME, users=(user_with_themes, user_with_both)
        )
        sitemap = AccountSitemap()
        items = list(sitemap.items())
        assert items == [
            (
                theme.last_updated,
                reverse('users.profile', args=[user_with_both.id]),
                1,
                1,
            ),
            (
                theme.last_updated,
                reverse('users.profile', args=[user_with_themes.id]),
                1,
                1,
            ),
            (
                extension.last_updated,
                reverse('users.profile', args=[user_with_extensions.id]),
                1,
                1,
            ),
        ]

    @mock.patch('olympia.amo.sitemap.EXTENSIONS_BY_AUTHORS_PAGE_SIZE', 2)
    @mock.patch('olympia.amo.sitemap.THEMES_BY_AUTHORS_PAGE_SIZE', 3)
    def test_pagination(self):
        user_with_themes = user_factory()
        user_with_extensions = user_factory()
        user_with_both = user_factory()
        user_factory(is_public=True)  # marked as public, but no addons.
        addon_factory(users=(user_with_extensions, user_with_both))
        addon_factory(
            type=amo.ADDON_STATICTHEME, users=(user_with_themes, user_with_both)
        )

        extra_extension_a = addon_factory(users=(user_with_extensions, user_with_both))
        extra_extension_b = addon_factory(users=(user_with_extensions, user_with_both))
        extra_theme_a = addon_factory(
            type=amo.ADDON_STATICTHEME, users=(user_with_themes, user_with_both)
        )
        extra_theme_b = addon_factory(
            type=amo.ADDON_STATICTHEME, users=(user_with_themes, user_with_both)
        )
        extra_theme_c = addon_factory(
            type=amo.ADDON_STATICTHEME, users=(user_with_themes, user_with_both)
        )

        sitemap = AccountSitemap()
        paginated_items = list(sitemap.items())
        assert paginated_items == [
            (
                extra_theme_c.last_updated,
                reverse('users.profile', args=[user_with_both.id]),
                1,
                1,
            ),
            (
                extra_theme_c.last_updated,
                reverse('users.profile', args=[user_with_both.id]),
                2,
                1,
            ),
            (
                extra_theme_c.last_updated,
                reverse('users.profile', args=[user_with_both.id]),
                1,
                2,
            ),
            (
                extra_theme_c.last_updated,
                reverse('users.profile', args=[user_with_themes.id]),
                1,
                1,
            ),
            (
                extra_theme_c.last_updated,
                reverse('users.profile', args=[user_with_themes.id]),
                1,
                2,
            ),
            (
                extra_extension_b.last_updated,
                reverse('users.profile', args=[user_with_extensions.id]),
                1,
                1,
            ),
            (
                extra_extension_b.last_updated,
                reverse('users.profile', args=[user_with_extensions.id]),
                2,
                1,
            ),
        ]
        # repeat, but after changing some of the addons so they wouldn't be visible
        extra_theme_a.update(status=amo.STATUS_NOMINATED)
        assert list(AccountSitemap().items()) == [
            # now only one page of themes for both users
            (
                extra_theme_c.last_updated,
                reverse('users.profile', args=[user_with_both.id]),
                1,
                1,
            ),
            (
                extra_theme_c.last_updated,
                reverse('users.profile', args=[user_with_both.id]),
                2,
                1,
            ),
            (
                extra_theme_c.last_updated,
                reverse('users.profile', args=[user_with_themes.id]),
                1,
                1,
            ),
            (
                extra_extension_b.last_updated,
                reverse('users.profile', args=[user_with_extensions.id]),
                1,
                1,
            ),
            (
                extra_extension_b.last_updated,
                reverse('users.profile', args=[user_with_extensions.id]),
                2,
                1,
            ),
        ]
        user_with_both.addonuser_set.filter(addon=extra_extension_a).update(
            listed=False
        )
        assert list(AccountSitemap().items()) == [
            (
                extra_theme_c.last_updated,
                reverse('users.profile', args=[user_with_both.id]),
                1,
                1,
            ),
            (
                extra_theme_c.last_updated,
                reverse('users.profile', args=[user_with_themes.id]),
                1,
                1,
            ),
            (
                extra_extension_b.last_updated,
                reverse('users.profile', args=[user_with_extensions.id]),
                1,
                1,
            ),
            # user_with_extensions still has 2 pages of extensions though
            (
                extra_extension_b.last_updated,
                reverse('users.profile', args=[user_with_extensions.id]),
                2,
                1,
            ),
        ]
        extra_theme_c.delete()
        assert list(AccountSitemap().items()) == [
            # the date used for lastmod has changed
            (
                extra_theme_b.last_updated,
                reverse('users.profile', args=[user_with_both.id]),
                1,
                1,
            ),
            (
                extra_theme_b.last_updated,
                reverse('users.profile', args=[user_with_themes.id]),
                1,
                1,
            ),
            (
                extra_extension_b.last_updated,
                reverse('users.profile', args=[user_with_extensions.id]),
                1,
                1,
            ),
            # user_with_extensions still has 2 pages of extensions though
            (
                extra_extension_b.last_updated,
                reverse('users.profile', args=[user_with_extensions.id]),
                2,
                1,
            ),
        ]
        # and check that deleting roles works too
        user_with_both.addonuser_set.filter(addon=extra_theme_b).update(
            role=amo.AUTHOR_ROLE_DELETED
        )
        assert list(AccountSitemap().items()) == [
            # the date used for lastmod has changed, and the order too
            (
                extra_theme_b.last_updated,
                reverse('users.profile', args=[user_with_themes.id]),
                1,
                1,
            ),
            (
                extra_extension_b.last_updated,
                reverse('users.profile', args=[user_with_both.id]),
                1,
                1,
            ),
            (
                extra_extension_b.last_updated,
                reverse('users.profile', args=[user_with_extensions.id]),
                1,
                1,
            ),
            (
                extra_extension_b.last_updated,
                reverse('users.profile', args=[user_with_extensions.id]),
                2,
                1,
            ),
        ]

    @mock.patch('olympia.amo.sitemap.EXTENSIONS_BY_AUTHORS_PAGE_SIZE', 2)
    @mock.patch('olympia.amo.sitemap.THEMES_BY_AUTHORS_PAGE_SIZE', 1)
    def test_android(self):
        # users with just themes on Android won't be included
        user_with_themes = user_factory()
        user_with_extensions = user_factory()
        user_with_both = user_factory()
        user_factory(is_public=True)  # marked as public, but no addons.
        extension = addon_factory(
            users=(user_with_extensions, user_with_both),
            version_kw={'application': amo.ANDROID.id},
        )
        self.make_addon_promoted(extension, RECOMMENDED, approve_version=True)
        extra_extension_a = addon_factory(
            users=(user_with_extensions, user_with_both),
            version_kw={'application': amo.ANDROID.id},
        )
        self.make_addon_promoted(extra_extension_a, RECOMMENDED, approve_version=True)
        extra_extension_b = addon_factory(
            users=(user_with_extensions, user_with_both),
            version_kw={'application': amo.ANDROID.id},
        )

        # and some addons that should be ignored
        addon_factory(
            type=amo.ADDON_STATICTHEME,
            users=(user_with_themes, user_with_both),
            version_kw={'application': amo.ANDROID.id},
        )
        addon_factory(
            type=amo.ADDON_STATICTHEME,
            users=(user_with_themes, user_with_both),
            version_kw={'application': amo.ANDROID.id},
        )
        firefox_addon = addon_factory(
            type=amo.ADDON_EXTENSION,
            users=(user_with_extensions, user_with_both),
            version_kw={'application': amo.FIREFOX.id},
        )
        self.make_addon_promoted(firefox_addon, RECOMMENDED, approve_version=True)

        # there would be 3 addons but one of them isn't promoted
        with override_url_prefix(app_name='android'):
            assert list(AccountSitemap().items()) == [
                (
                    extra_extension_a.last_updated,
                    reverse('users.profile', args=[user_with_both.id]),
                    1,
                    1,
                ),
                (
                    extra_extension_a.last_updated,
                    reverse('users.profile', args=[user_with_extensions.id]),
                    1,
                    1,
                ),
            ]

        self.make_addon_promoted(extra_extension_b, RECOMMENDED, approve_version=True)
        with override_url_prefix(app_name='android'):
            assert list(AccountSitemap().items()) == [
                (
                    extra_extension_b.last_updated,
                    reverse('users.profile', args=[user_with_both.id]),
                    1,
                    1,
                ),
                (
                    extra_extension_b.last_updated,
                    reverse('users.profile', args=[user_with_both.id]),
                    2,
                    1,
                ),
                (
                    extra_extension_b.last_updated,
                    reverse('users.profile', args=[user_with_extensions.id]),
                    1,
                    1,
                ),
                (
                    extra_extension_b.last_updated,
                    reverse('users.profile', args=[user_with_extensions.id]),
                    2,
                    1,
                ),
            ]
        # delete user_with_both from extra_extension_b
        user_with_both.addonuser_set.filter(addon=extra_extension_b).update(
            role=amo.AUTHOR_ROLE_DELETED
        )
        with override_url_prefix(app_name='android'):
            assert list(AccountSitemap().items()) == [
                (
                    extra_extension_b.last_updated,
                    reverse('users.profile', args=[user_with_extensions.id]),
                    1,
                    1,
                ),
                (
                    extra_extension_b.last_updated,
                    reverse('users.profile', args=[user_with_extensions.id]),
                    2,
                    1,
                ),
                (
                    extra_extension_a.last_updated,
                    reverse('users.profile', args=[user_with_both.id]),
                    1,
                    1,
                ),
            ]


def test_tag_pages_sitemap():
    # without any addons we should still generate a url for each tag page
    empty_tag_pages = list(TagPagesSitemap().items())
    assert empty_tag_pages == [(tag, 1) for tag in Tag.objects.all()]
    # add some addons and check we generate extra pages when frontend would paginate
    zoom_tag = Tag.objects.get(tag_text='zoom')
    shopping_tag = Tag.objects.get(tag_text='shopping')
    addon_factory(tags=(zoom_tag.tag_text, shopping_tag.tag_text))
    addon_factory(tags=(zoom_tag.tag_text, shopping_tag.tag_text))

    addon_factory(tags=(zoom_tag.tag_text,))
    addon_factory(tags=(zoom_tag.tag_text,))
    addon_factory(tags=(zoom_tag.tag_text,))
    addon_factory(tags=(shopping_tag.tag_text,), status=amo.STATUS_NOMINATED)
    addon_factory(
        tags=(shopping_tag.tag_text,), version_kw={'application': amo.ANDROID.id}
    )
    # should be 4 addons tagged with shopping (one not public, one not compatible with
    # Firefox, so 2 public), and 5 tagged with zoom

    patched_drf_setting = dict(settings.REST_FRAMEWORK)
    patched_drf_setting['PAGE_SIZE'] = 2
    with override_settings(REST_FRAMEWORK=patched_drf_setting):
        tag_pages_with_addons = list(TagPagesSitemap().items())
    # two extra urls, for second+third zoom tag pages, because PAGE_SIZE = 2
    extra_2 = (zoom_tag, 2)
    extra_3 = (zoom_tag, 3)
    assert extra_2 in tag_pages_with_addons
    assert extra_3 in tag_pages_with_addons
    assert set(tag_pages_with_addons) - set(empty_tag_pages) == {extra_2, extra_3}

    # now limit the number of items that would be paginated over so zoom count == 4
    with override_settings(REST_FRAMEWORK=patched_drf_setting, ES_MAX_RESULT_WINDOW=4):
        tag_pages_limited = list(TagPagesSitemap().items())
    assert extra_3 not in tag_pages_limited
    assert set(tag_pages_limited) - set(empty_tag_pages) == {extra_2}


def test_get_sitemap_section_pages():
    addon_factory()
    addon_factory()
    addon_factory()

    sitemaps = get_sitemaps()
    pages = get_sitemap_section_pages(sitemaps)
    assert pages == [
        ('amo', None, 1),
        ('addons', 'firefox', 1),
        ('addons', 'android', 1),
        ('categories', 'firefox', 1),
        ('collections', 'firefox', 1),
        ('users', 'firefox', 1),
        ('users', 'android', 1),
        ('tags', 'firefox', 1),
        ('tags', 'android', 1),
    ]
    with mock.patch.object(AddonSitemap, 'limit', 25):
        pages = get_sitemap_section_pages(sitemaps)
        # 2 pages per addon * 3 addons * 10 locales = 60 urls for addons; 3 pages @ 25pp
        assert len(sitemaps.get(('addons', amo.FIREFOX))._items()) == 60
        assert pages == [
            ('amo', None, 1),
            ('addons', 'firefox', 1),
            ('addons', 'firefox', 2),
            ('addons', 'firefox', 3),
            ('addons', 'android', 1),
            ('categories', 'firefox', 1),
            ('collections', 'firefox', 1),
            ('users', 'firefox', 1),
            ('users', 'android', 1),
            ('tags', 'firefox', 1),
            ('tags', 'android', 1),
        ]

    # test the default pagination limit

    def items_mock(self):
        return [
            AccountSitemap.item_tuple(datetime.now(), user_id, 7, 8)
            for user_id in range(0, 401)
        ]

    with mock.patch.object(AccountSitemap, 'items', items_mock):
        # 401 mock user pages * 10 locales = 4010 urls for addons; 3 pages @ 2000pp
        pages = get_sitemap_section_pages(sitemaps)
        assert pages == [
            ('amo', None, 1),
            ('addons', 'firefox', 1),
            ('addons', 'android', 1),
            ('categories', 'firefox', 1),
            ('collections', 'firefox', 1),
            ('users', 'firefox', 1),
            ('users', 'firefox', 2),
            ('users', 'firefox', 3),
            ('users', 'android', 1),
            ('users', 'android', 2),
            ('users', 'android', 3),
            ('tags', 'firefox', 1),
            ('tags', 'android', 1),
        ]


def test_render_index_xml():
    with mock.patch('olympia.amo.sitemap.get_sitemap_section_pages') as pages_mock:
        pages_mock.return_value = [
            ('amo', None, 1),
            ('addons', 'firefox', 1),
            ('addons', 'firefox', 2),
            ('addons', 'android', 1),
            ('addons', 'android', 2),
        ]
        built = render_index_xml(sitemaps={})

        with open(os.path.join(TEST_SITEMAPS_DIR, 'sitemap.xml')) as sitemap:
            assert built == sitemap.read()


def test_sitemap_render():
    def items_mock(self):
        return [
            AddonSitemap.item_tuple(
                datetime(2020, 10, 2, 0, 0, 0),
                reverse('addons.detail', args=['delicious-barbeque']),
            ),
            AddonSitemap.item_tuple(
                datetime(2020, 10, 1, 0, 0, 0),
                reverse('addons.detail', args=['spicy-sandwich']),
            ),
            AddonSitemap.item_tuple(
                datetime(2020, 9, 30, 0, 0, 0),
                reverse('addons.detail', args=['delicious-chocolate']),
            ),
            AddonSitemap.item_tuple(
                datetime(2020, 10, 2, 0, 0, 0),
                reverse('addons.ratings.list', args=['delicious-barbeque']),
            ),
            AddonSitemap.item_tuple(
                datetime(2020, 10, 1, 0, 0, 0),
                reverse('addons.ratings.list', args=['spicy-sandwich']),
            ),
            AddonSitemap.item_tuple(
                datetime(2020, 9, 30, 0, 0, 0),
                reverse('addons.ratings.list', args=['delicious-chocolate']),
            ),
        ]

    with mock.patch.object(AddonSitemap, 'items', items_mock):
        firefox_built = AddonSitemap().render('firefox', 1)

        firefox_file = os.path.join(TEST_SITEMAPS_DIR, 'sitemap-addons-firefox.xml')
        with open(firefox_file) as sitemap:
            assert firefox_built == sitemap.read()

        android_built = AddonSitemap().render('android', 1)
        android_file = os.path.join(TEST_SITEMAPS_DIR, 'sitemap-addons-android.xml')
        with open(android_file) as sitemap:
            assert android_built == sitemap.read()


def test_get_sitemap_path():
    basepath = settings.SITEMAP_STORAGE_PATH
    assert get_sitemap_path(None, None) == f'{basepath}/sitemap.xml'
    assert get_sitemap_path('foo', None) == f'{basepath}/foo/sitemap.xml'
    assert get_sitemap_path('foo', 'bar') == f'{basepath}/foo/bar/1/01/1.xml'
    assert get_sitemap_path('foo', None, 1) == f'{basepath}/foo/sitemap.xml'
    assert get_sitemap_path('foo', None, 2) == f'{basepath}/foo/2.xml'
    assert get_sitemap_path('foo', None, 89) == f'{basepath}/foo/89.xml'
    assert get_sitemap_path('foo', None, 4321) == f'{basepath}/foo/4321.xml'
    assert get_sitemap_path('foo', 'bar', 1) == f'{basepath}/foo/bar/1/01/1.xml'
    assert get_sitemap_path('foo', 'bar', 2) == f'{basepath}/foo/bar/2/02/2.xml'
    assert get_sitemap_path('foo', 'bar', 89) == f'{basepath}/foo/bar/9/89/89.xml'
    assert get_sitemap_path('foo', 'bar', 4321) == f'{basepath}/foo/bar/1/21/4321.xml'
