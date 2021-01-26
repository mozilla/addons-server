# -*- coding: utf-8 -*-
import collections

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase
from olympia.constants.applications import APPS
from olympia.constants.base import ADDON_EXTENSION, ADDON_STATICTHEME
from olympia.constants.categories import CATEGORIES
from olympia.landfill.generators import _yield_name_and_cat, create_addon
from olympia.versions.models import Version


class _BaseAddonGeneratorMixin(object):
    def test_tinyset(self):
        size = 4
        data = list(_yield_name_and_cat(size, self.app, self.type))
        assert len(data) == size
        # Names are unique.
        assert len(set(addonname for addonname, cat in data)) == size
        # Size is smaller than name list, so no names end in numbers.
        assert not any(addonname[-1].isdigit() for addonname, cat in data)

    def test_smallset(self):
        size = len(CATEGORIES[self.app.id][self.type]) * 6
        data = list(_yield_name_and_cat(size, self.app, self.type))
        assert len(data) == size
        # Addons are split up equally within each categories.
        categories = collections.defaultdict(int)
        for addonname, category in data:
            categories[category.slug] += 1
        length = len(CATEGORIES[self.app.id][self.type])
        assert set(categories.values()) == set([size / length])
        assert len(set(addonname for addonname, cat in data)) == size
        assert not any(addonname[-1].isdigit() for addonname, cat in data)

    def test_bigset(self):
        size = 300
        data = list(_yield_name_and_cat(size, self.app, self.type))
        assert len(data) == size
        categories = collections.defaultdict(int)
        for addonname, cat in data:
            categories[cat.id] += 1
        # Addons are spread between categories evenly - the difference
        # between the largest and smallest category is less than 2.
        assert max(categories.values()) - min(categories.values()) < 2
        assert len(set(addonname for addonname, cat in data)) == size


class FirefoxAddonGeneratorTests(_BaseAddonGeneratorMixin, TestCase):
    app = APPS['firefox']
    type = ADDON_EXTENSION


class AndroidAddonGeneratorTests(_BaseAddonGeneratorMixin, TestCase):
    app = APPS['android']
    type = ADDON_EXTENSION


class ThemeGeneratorTests(_BaseAddonGeneratorMixin, TestCase):
    app = APPS['firefox']
    type = ADDON_STATICTHEME


class CreateGeneratorTests(TestCase):
    def test_create_addon(self):
        addon = create_addon('foo', APPS['android'])
        assert Addon.objects.last().name == addon.name
        assert amo.STATUS_APPROVED == addon.status
        assert Version.objects.last() == addon._current_version
        assert addon.guid
        assert addon.slug
