# -*- coding: utf-8 -*-
from olympia.addons.models import Category
from olympia.amo.tests import TestCase
from olympia.constants.applications import APPS
from olympia.constants.base import ADDON_EXTENSION, ADDON_PERSONA
from olympia.constants.categories import CATEGORIES
from olympia.landfill.categories import generate_categories


class CategoriesTests(TestCase):
    def test_categories_themes_generation(self):
        data = generate_categories(APPS['firefox'], ADDON_PERSONA)
        assert len(data) == Category.objects.all().count()
        assert len(data) == 15

    def test_categories_addons_generation(self):
        data = generate_categories(APPS['android'], ADDON_EXTENSION)
        assert len(data) == Category.objects.all().count()
        assert len(data) == 11

        category = Category.objects.get(
            id=CATEGORIES[APPS['android'].id][ADDON_EXTENSION]['shopping'].id
        )
        assert unicode(category.name) == u'Shopping'

        # Re-generating should not create any more.
        data = generate_categories(APPS['android'], ADDON_EXTENSION)
        assert len(data) == Category.objects.all().count()
        assert len(data) == 11

        # Name should still be the same.
        category = Category.objects.get(
            id=CATEGORIES[APPS['android'].id][ADDON_EXTENSION]['shopping'].id
        )
        assert unicode(category.name) == u'Shopping'
