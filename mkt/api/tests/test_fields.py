# -*- coding: utf-8 -*-
from nose.tools import eq_

from amo.tests import TestCase
from mkt.api.fields import TranslationSerializerField
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp
from translations.models import Translation


class TestTranslationSerializerField(TestCase):
    fixtures = fixture('user_2519', 'webapp_337141')

    def test_from_native(self):
        data = u'Translatiön'
        field = TranslationSerializerField()
        result = field.from_native(data)
        eq_(result, data)

        data = {
            'fr': u'Non mais Allô quoi !',
            'en-US': u'No But Hello what!'
        }
        field = TranslationSerializerField()
        result = field.from_native(data)
        eq_(result, data)

        data = ['Bad Data']
        field = TranslationSerializerField()
        result = field.from_native(data)
        eq_(result, unicode(data))

    def test_field_from_native_strip(self):
        data = {
            'fr': u'  Non mais Allô quoi ! ',
            'en-US': u''
        }
        field = TranslationSerializerField()
        result = field.from_native(data)
        eq_(result, {'fr': u'Non mais Allô quoi !', 'en-US': u''})

    def test_field_to_native(self):
        app = Webapp.objects.get(pk=337141)
        field = TranslationSerializerField()
        result = field.field_to_native(app, 'name')
        expected = {
            'en-US': Translation.objects.get(id=app.name.id, locale='en-US'),
            'es': Translation.objects.get(id=app.name.id, locale='es')
        }
        eq_(result, expected)

        result = field.field_to_native(app, 'description')
        expected = {
            'en-US': Translation.objects.get(id=app.description.id, 
                                             locale='en-US'),
        }
        eq_(result, expected)
