# -*- coding: utf-8 -*-
from nose.tools import ok_

import amo
import amo.tests
from addons.models import Category
from constants.applications import APPS
from landfill.categories import generate_categories


class CategoriesTests(amo.tests.TestCase):

    def test_categories_themes_generation(self):
        data = generate_categories()
        assert len(data) == Category.objects.all().count()
        assert len(data) == 15

    def test_categories_themes_translations(self):
        with self.activate(locale='es'):
            data = generate_categories()
            ok_(unicode(data[0].name).startswith(u'(español) '))

    def test_categories_addons_generation(self):
        data = generate_categories(APPS['android'])
        assert len(data) == Category.objects.all().count()
        assert len(data) == 10

    def test_categories_addons_translations(self):
        with self.activate(locale='es'):
            data = generate_categories(APPS['android'])
            ok_(unicode(data[0].name).startswith(u'(español) '))
