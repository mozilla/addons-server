# -*- coding: utf-8 -*-
from django import http
from django.core.cache import cache

from mock import patch
from nose.tools import eq_, assert_raises
from pyquery import PyQuery as pq

import test_utils

import amo
from amo.urlresolvers import reverse
from amo.helpers import urlparams
from addons.models import Addon, Category
from browse import views
from browse.views import locale_display_name


def test_locale_display_name():

    def check(locale, english, native):
        actual = locale_display_name(locale)
        eq_(actual, (english, native))

    check('el', 'Greek', u'Ελληνικά')
    check('el-XX', 'Greek', u'Ελληνικά')
    assert_raises(KeyError, check, 'fake-lang', '', '')


class TestLanguageTools(test_utils.TestCase):
    fixtures = ['browse/test_views']

    def setUp(self):
        cache.clear()
        self.url = reverse('browse.language_tools')
        response = self.client.get(self.url, follow=True)
        self.locales = response.context['locales']

    def test_sorting(self):
        """The locales should be sorted by English display name."""
        displays = [locale.display for _, locale in self.locales]
        eq_(displays, sorted(displays))

    def test_native_missing_region(self):
        """
        If we had to strip a locale's region to find a display name, we
        append it to the native name for disambiguation.
        """
        el = dict(self.locales)['el-XX']
        assert el.native.endswith(' (el-xx)')

    def test_missing_locale(self):
        """If we don't know about a locale, show the addon name and locale."""
        wa = dict(self.locales)['wa']
        eq_(wa.display, 'Walloon Language Pack (wa)')
        eq_(wa.native, '')

    def test_packs_and_dicts(self):
        ca = dict(self.locales)['ca-valencia']
        eq_(len(ca.dicts), 1)
        eq_(len(ca.packs), 2)

    def test_empty_target_locale(self):
        """Make sure nothing breaks with empty target locales."""
        for addon in Addon.objects.all():
            addon.target_locale = ''
            addon.save()
        response = self.client.get(self.url, follow=True)
        eq_(response.status_code, 200)
        eq_(response.context['locales'], [])

    def test_null_target_locale(self):
        """Make sure nothing breaks with null target locales."""
        for addon in Addon.objects.all():
            addon.target_locale = None
            addon.save()
        response = self.client.get(self.url, follow=True)
        eq_(response.status_code, 200)
        eq_(response.context['locales'], [])


class TestThemes(test_utils.TestCase):
    fixtures = ['base/fixtures']

    def setUp(self):
        # Make all the add-ons themes.
        for addon in Addon.objects.all():
            addon.type_id = amo.ADDON_THEME
            addon.save()

        self.base_url = reverse('browse.themes')
        self.exp_url = urlparams(self.base_url, unreviewed=True)

    def test_default_sort(self):
        """Default sort should be by downloads."""
        response = self.client.get(self.base_url)
        eq_(response.context['sorting'], 'downloads')

    def test_unreviewed(self):
        # Only 3 without unreviewed.
        response = self.client.get(self.base_url)
        eq_(len(response.context['themes'].object_list), 8)

        response = self.client.get(self.exp_url)
        eq_(len(response.context['themes'].object_list), 10)

    def _get_sort(self, sort):
        response = self.client.get(urlparams(self.exp_url, sort=sort))
        eq_(response.context['sorting'], sort)
        return [a.id for a in response.context['themes'].object_list]

    def test_download_sort(self):
        ids = self._get_sort('downloads')
        eq_(ids, [55, 1843, 73, 3615, 5369, 7172, 6113, 10869, 6704, 40])

    def test_name_sort(self):
        ids = self._get_sort('name')
        eq_(ids, [55, 3615, 1843, 6704, 10869, 7172, 40, 5369, 73, 6113])

    def test_created_sort(self):
        ids = self._get_sort('created')
        eq_(ids, [10869, 7172, 6704, 6113, 5369, 3615, 55, 73, 1843, 40])

    def test_updated_sort(self):
        ids = self._get_sort('updated')
        eq_(ids, [6113, 3615, 7172, 5369, 10869, 6704, 1843, 73, 40, 55])

    def test_rating_sort(self):
        ids = self._get_sort('rating')
        eq_(ids, [6113, 7172, 1843, 6704, 10869, 40, 5369, 3615, 55, 73])


class TestCategoryPages(test_utils.TestCase):
    fixtures = ['base/fixtures']

    def test_browsing_urls(self):
        """Every browse page URL exists."""
        for _, slug in amo.ADDON_SLUGS.items():
            assert reverse('browse.%s' % slug, args=['something'])

    def test_matching_opts(self):
        """Every filter on landing pages is available on listing pages."""
        for key, _ in views.CategoryLandingFilter.opts:
            if key != 'featured':
                assert key in dict(views.AddonFilter.opts)

    @patch('browse.views.category_landing')
    def test_goto_category_landing(self, landing_mock):
        """We hit a landing page if there's a category and no sorting."""
        landing_mock.return_value = http.HttpResponse()

        self.client.get(reverse('browse.extensions'))
        assert not landing_mock.called

        slug = Category.objects.all()[0].slug
        category_url = reverse('browse.extensions', args=[slug])
        self.client.get('%s?sort=created' % category_url)
        assert not landing_mock.called

        self.client.get(category_url)
        assert landing_mock.called

    def test_creatured_addons(self):
        """Make sure the creatured add-ons are for the right category."""
        # Featured in bookmarks.
        url = reverse('browse.extensions', args=['bookmarks'])
        response = self.client.get(url, follow=True)
        creatured = response.context['filter'].all()['featured']
        eq_(len(creatured), 1)
        eq_(creatured[0].id, 3615)

        # Not featured in search-tools.
        url = reverse('browse.extensions', args=['search-tools'])
        response = self.client.get(url, follow=True)
        creatured = response.context['filter'].all()['featured']
        eq_(len(creatured), 0)

    def test_added_date(self):
        url = reverse('browse.extensions') + '?sort=created'
        doc = pq(self.client.get(url).content)
        s = doc('.featured .item .updated').text()
        assert s.strip().startswith('Added'), s
