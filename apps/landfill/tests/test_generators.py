# -*- coding: utf-8 -*-
import collections
from nose.tools import ok_

import amo
import amo.tests
from addons.models import Addon, Persona
from constants.applications import APPS
from landfill.categories import addons_categories, themes_categories
from landfill.generators import _yield_name_and_cat, create_addon, create_theme
from versions.models import Version


class _BaseAddonGeneratorMixin(object):

    def test_tinyset(self):
        size = 4
        data = list(_yield_name_and_cat(size, self.app))
        assert len(data) == size
        assert len(set(addonname for addonname, cat in data)) == size
        # Size is smaller than name list, so no names end in numbers.
        ok_(not any(addonname[-1].isdigit() for addonname, cat in data))

    def test_smallset(self):
        size = 60
        data = list(_yield_name_and_cat(size, self.app))
        assert len(data) == size
        # Addons are split up equally within each categories.
        categories = collections.defaultdict(int)
        for addonname, category in data:
            categories[category.slug] += 1
        if self.app is None:
            length = len(themes_categories)
        else:
            length = len(addons_categories[self.app.short])
        assert set(categories.values()) == set([size / length])
        assert len(set(addonname for addonname, cat in data)) == size
        ok_(not any(addonname[-1].isdigit() for addonname, cat in data))

    def test_bigset(self):
        size = 300
        data = list(_yield_name_and_cat(size, self.app))
        assert len(data) == size
        categories = collections.defaultdict(int)
        for addonname, cat in data:
            categories[cat] += 1
        # Addons are spread between categories evenly - the difference
        # between the largest and smallest category is less than 2.
        ok_(max(categories.values()) - min(categories.values()) < 2)
        assert len(set(addonname for addonname, cat in data)) == size


class FirefoxAddonGeneratorTests(_BaseAddonGeneratorMixin, amo.tests.TestCase):
    app = APPS['firefox']


class ThunderbirdAddonGeneratorTests(_BaseAddonGeneratorMixin,
                                     amo.tests.TestCase):
    app = APPS['thunderbird']


class AndroidAddonGeneratorTests(_BaseAddonGeneratorMixin, amo.tests.TestCase):
    app = APPS['android']


class SeamonkeyAddonGeneratorTests(_BaseAddonGeneratorMixin,
                                   amo.tests.TestCase):
    app = APPS['seamonkey']


class ThemeGeneratorTests(_BaseAddonGeneratorMixin, amo.tests.TestCase):
    app = None


class CreateGeneratorTests(amo.tests.TestCase):

    def test_create_addon(self):
        addon = create_addon('foo', 'icon/default', APPS['android'])
        assert Addon.objects.last().name == addon.name
        assert amo.STATUS_PUBLIC == addon.status
        assert Version.objects.last() == addon._current_version

    def test_create_theme(self):
        theme = create_theme('bar')
        assert Addon.objects.last().name == theme.name
        assert amo.STATUS_PUBLIC == theme.status
        assert amo.ADDON_PERSONA == theme.type
        assert Persona.objects.last() == theme.persona
        assert Version.objects.last() == theme._current_version
