# -*- coding: utf-8 -*-
from django.core.cache import cache

from nose.tools import eq_, assert_raises

import test_utils

from amo.urlresolvers import reverse
from browse.views import locale_display_name


def test_locale_display_name():
    def check(locale, english, native):
        actual = locale_display_name(locale)
        eq_(actual, (english, native))

    check('el', 'Greek', u'Ελληνικά')
    check('el-XXX', 'Greek', u'Ελληνικά')
    assert_raises(KeyError, check, 'fake-lang', '', '')


class TestView(test_utils.TestCase):
    fixtures = ['browse/test_views']

    def setUp(self):
        cache.clear()
        url = reverse('browse.language_tools')
        response = self.client.get(url, follow=True)
        self.locales = response.context['locales']

    def test_sorting(self):
        """The locales should be sorted by English display name."""
        displays = [locale.display for lang, locale in self.locales]
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
