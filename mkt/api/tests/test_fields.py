# -*- coding: utf-8 -*-
from nose.tools import eq_
from rest_framework.request import Request
from rest_framework.serializers import Serializer
from rest_framework.test import APIRequestFactory

from amo.tests import TestCase
from mkt.api.fields import TranslationSerializerField
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp
from translations.models import Translation


class TestTranslationSerializerField(TestCase):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        super(TestTranslationSerializerField, self).setUp()
        self.factory = APIRequestFactory()
        self.app = Webapp.objects.get(pk=337141)

    def _test_expected_dict(self, field):
        result = field.field_to_native(self.app, 'name')
        expected = {
            'en-US': unicode(Translation.objects.get(id=self.app.name.id,
                                                     locale='en-US')),
            'es': unicode(Translation.objects.get(id=self.app.name.id,
                                                  locale='es')),
        }
        eq_(result, expected)

        result = field.field_to_native(self.app, 'description')
        expected = {
            'en-US': Translation.objects.get(id=self.app.description.id,
                                             locale='en-US'),
        }
        eq_(result, expected)

    def _test_expected_single_string(self, field):
        result = field.field_to_native(self.app, 'name')
        expected = unicode(self.app.name)
        eq_(result, expected)

        result = field.field_to_native(self.app, 'description')
        expected = unicode(self.app.description)
        eq_(result, expected)

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
        field = TranslationSerializerField()
        self._test_expected_dict(field)

    def test_field_to_native_empty_context(self):
        mock_serializer = Serializer()
        mock_serializer.context = {}
        field = TranslationSerializerField()
        field.initialize(mock_serializer, 'name')
        self._test_expected_dict(field)

    def test_field_to_native_request_POST(self):
        request = Request(self.factory.post('/'))
        mock_serializer = Serializer()
        mock_serializer.context = {'request': request}
        field = TranslationSerializerField()
        field.initialize(mock_serializer, 'name')
        self._test_expected_dict(field)

    def test_field_to_native_request_GET(self):
        request = Request(self.factory.get('/'))
        mock_serializer = Serializer()
        mock_serializer.context = {'request': request}
        field = TranslationSerializerField()
        field.initialize(mock_serializer, 'name')
        self._test_expected_dict(field)

    def test_field_to_native_request_GET_lang(self):
        """
        Pass a lang in the query string, expect to have a single string
        returned instead of an object.
        """
        # Note that we don't go through the middlewares etc so the actual
        # language for the process isn't changed, we don't care as
        # _expect_single_string() method simply tests with the current language,
        # whatever it is.
        request = Request(self.factory.get('/', {'lang': 'lol'}))
        eq_(request.GET['lang'], 'lol')
        mock_serializer = Serializer()
        mock_serializer.context = {'request': request}
        field = TranslationSerializerField()
        field.initialize(mock_serializer, 'name')
        self._test_expected_single_string(field)
