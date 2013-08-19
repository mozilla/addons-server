# -*- coding: utf-8 -*-
from nose.tools import eq_

from amo.tests import TestCase
from mkt.api.fields import TranslationSerializerField


class TestTranslationSerializerField(TestCase):
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

    def test_field_to_native(self):
        class TestObject(object):
            test_field = u'Yes We Can'

        field = TranslationSerializerField()
        result = field.field_to_native(TestObject(), 'test_field')
        eq_(result, TestObject.test_field)
