# -*- coding: utf-8 -*-
import collections
from nose.tools import eq_, ok_

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.addons.models import Addon, Persona
from olympia.constants.applications import APPS
from olympia.landfill.categories import addons_categories, themes_categories
from olympia.landfill.generators import (
    _yield_name_and_cat, create_addon, create_theme)
from olympia.versions.models import Version


class _BaseAddonGeneratorMixin(object):

    def test_tinyset(self):
        size = 4
        data = list(_yield_name_and_cat(size, self.app))
        eq_(len(data), size)
        # Names are unique.
        eq_(len(set(addonname for addonname, cat in data)), size)
        # Size is smaller than name list, so no names end in numbers.
        ok_(not any(addonname[-1].isdigit() for addonname, cat in data))

    def test_smallset(self):
        size = 60
        data = list(_yield_name_and_cat(size, self.app))
        eq_(len(data), size)
        # Addons are split up equally within each categories.
        categories = collections.defaultdict(int)
        for addonname, category in data:
            categories[category.slug] += 1
        if self.app is None:
            length = len(themes_categories)
        else:
            length = len(addons_categories[self.app.short])
        eq_(set(categories.values()), set([size / length]))
        eq_(len(set(addonname for addonname, cat in data)), size)
        ok_(not any(addonname[-1].isdigit() for addonname, cat in data))

    def test_bigset(self):
        size = 300
        data = list(_yield_name_and_cat(size, self.app))
        eq_(len(data), size)
        categories = collections.defaultdict(int)
        for addonname, cat in data:
            categories[cat] += 1
        # Addons are spread between categories evenly - the difference
        # between the largest and smallest category is less than 2.
        ok_(max(categories.values()) - min(categories.values()) < 2)
        eq_(len(set(addonname for addonname, cat in data)), size)


class FirefoxAddonGeneratorTests(_BaseAddonGeneratorMixin, TestCase):
    app = APPS['firefox']


class ThunderbirdAddonGeneratorTests(_BaseAddonGeneratorMixin,
                                     TestCase):
    app = APPS['thunderbird']


class AndroidAddonGeneratorTests(_BaseAddonGeneratorMixin, TestCase):
    app = APPS['android']


class SeamonkeyAddonGeneratorTests(_BaseAddonGeneratorMixin,
                                   TestCase):
    app = APPS['seamonkey']


class ThemeGeneratorTests(_BaseAddonGeneratorMixin, TestCase):
    app = None


class CreateGeneratorTests(TestCase):

    def test_create_addon(self):
        addon = create_addon('foo', 'icon/default', APPS['android'])
        eq_(Addon.objects.last().name, addon.name)
        eq_(amo.STATUS_PUBLIC, addon.status)
        eq_(Version.objects.last(), addon._current_version)

    def test_create_theme(self):
        theme = create_theme('bar')
        eq_(Addon.objects.last().name, theme.name)
        eq_(amo.STATUS_PUBLIC, theme.status)
        eq_(amo.ADDON_PERSONA, theme.type)
        eq_(Persona.objects.last(), theme.persona)
        eq_(Version.objects.last(), theme._current_version)
