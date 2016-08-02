# -*- coding: utf-8 -*-
from olympia.amo.tests import TestCase
from olympia.addons.models import Category
from olympia.constants.applications import APPS
from olympia.landfill.categories import generate_categories


class CategoriesTests(TestCase):

    def test_categories_themes_generation(self):
        data = generate_categories()
        assert len(data) == Category.objects.all().count()
        assert len(data) == 15

    def test_categories_addons_generation(self):
        data = generate_categories(APPS['android'])
        assert len(data) == Category.objects.all().count()
        assert len(data) == 10
