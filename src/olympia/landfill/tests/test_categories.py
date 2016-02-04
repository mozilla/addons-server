# -*- coding: utf-8 -*-
from nose.tools import eq_, ok_

from olympia.amo.tests import TestCase
from olympia.addons.models import Category
from olympia.constants.applications import APPS
from olympia.landfill.categories import generate_categories


class CategoriesTests(TestCase):

    def test_categories_themes_generation(self):
        data = generate_categories()
        eq_(len(data), Category.objects.all().count())
        eq_(len(data), 15)

    def test_categories_themes_translations(self):
        with self.activate(locale='es'):
            data = generate_categories()
            ok_(unicode(data[0].name).startswith(u'(español) '))

    def test_categories_addons_generation(self):
        data = generate_categories(APPS['android'])
        eq_(len(data), Category.objects.all().count())
        eq_(len(data), 10)

    def test_categories_addons_translations(self):
        with self.activate(locale='es'):
            data = generate_categories(APPS['android'])
            ok_(unicode(data[0].name).startswith(u'(español) '))
