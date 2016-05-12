# -*- coding: utf-8 -*-
from django.core.exceptions import ValidationError

from mock import Mock
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from olympia.addons.models import Addon
from olympia.api.fields import (
    ESTranslationSerializerField, ReverseChoiceField,
    TranslationSerializerField)
from olympia.amo.tests import addon_factory, TestCase
from olympia.translations.models import Translation


class TestReverseChoiceField(TestCase):
    def test_to_representation(self):
        """Test that when we return a reprensentation to the client, we convert
        the internal value in an human-readable format
        (e.g. a string constant)."""
        field = ReverseChoiceField(choices=(('internal', 'human'),))
        assert field.to_representation('internal') == 'human'

    def test_to_internal_value(self):
        """Test that when a client sends data in human-readable format
        (e.g. a string constant), we convert it to the internal format when
        converting data to internal value."""
        field = ReverseChoiceField(choices=(('internal', 'human'),))
        assert field.to_internal_value('human') == 'internal'

    def test_to_internal_value_invalid_choices(self):
        """Test that choices still matter, and you can't a) send the internal
        value or b) send an invalid value."""
        field = ReverseChoiceField(choices=(('internal', 'human'),))
        with self.assertRaises(serializers.ValidationError):
            field.to_internal_value('internal')


class TestTranslationSerializerField(TestCase):
    """
    Base test class for translation fields tests.

    This allows the same tests to be applied to TranslationSerializerField
    (MySQL) and ESTranslationSerializerField (ElasticSearch) since everything
    should work transparently regardless of where the data is coming from.
    """
    field_class = TranslationSerializerField

    def setUp(self):
        super(TestTranslationSerializerField, self).setUp()
        self.factory = APIRequestFactory()
        self.addon = addon_factory(description=u'Descrîption...')
        Translation.objects.create(id=self.addon.name.id, locale='es',
                                   localized_string=u'Name in Español')

    def _test_expected_dict(self, field, serializer=None):
        field.bind('name', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = {
            'en-US': unicode(Translation.objects.get(id=self.addon.name.id,
                                                     locale='en-US')),
            'es': unicode(Translation.objects.get(id=self.addon.name.id,
                                                  locale='es')),
        }
        assert result == expected

        field.source = None
        field.bind('description', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = {
            'en-US': Translation.objects.get(
                id=self.addon.description.id, locale='en-US'),
        }
        assert result == expected

    def _test_expected_single_string(self, field, serializer=None):
        field.bind('name', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = unicode(self.addon.name)
        assert result == expected

        field.source = None
        field.bind('description', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = unicode(self.addon.description)
        assert result == expected

    def test_to_representation(self):
        data = u'Translatiön'
        field = self.field_class()
        result = field.to_representation(data)
        assert result == data

    def test_to_representation_dict(self):
        data = {
            'fr': u'Non mais Allô quoi !',
            'en-US': u'No But Hello what!'
        }
        field = self.field_class()
        result = field.to_representation(data)
        assert result == data

    def test_to_internal_value_strip(self):
        data = {
            'fr': u'  Non mais Allô quoi ! ',
            'en-US': u''
        }
        field = self.field_class()
        result = field.to_internal_value(data)
        assert result == {'fr': u'Non mais Allô quoi !', 'en-US': u''}

    def test_wrong_locale_code(self):
        data = {
            'unknown-locale': 'some name',
        }
        field = self.field_class()
        with self.assertRaises(ValidationError) as exc:
            field.to_internal_value(data)
        assert exc.exception.message == (
            u"The language code 'unknown-locale' is invalid.")

    def test_none_type_locale_is_allowed(self):
        # None values are valid because they are used to nullify existing
        # translations in something like a PATCH.
        data = {
            'en-US': None,
        }
        field = self.field_class()
        result = field.to_internal_value(data)
        field.validate(result)
        assert result == data

    def test_get_attribute(self):
        field = self.field_class()
        self._test_expected_dict(field)

    def test_get_attribute_source(self):
        self.addon.mymock = Mock()
        self.addon.mymock.mymocked_field = self.addon.name
        field = self.field_class(source='mymock.mymocked_field')
        result = field.to_internal_value(field.get_attribute(self.addon))
        expected = {
            'en-US': unicode(Translation.objects.get(id=self.addon.name.id,
                                                     locale='en-US')),
            'es': unicode(Translation.objects.get(id=self.addon.name.id,
                                                  locale='es')),
        }
        assert result == expected

    def test_get_attribute_empty_context(self):
        mock_serializer = serializers.Serializer()
        mock_serializer.context = {}
        field = self.field_class()
        self._test_expected_dict(field, mock_serializer)

    def test_field_get_attribute_request_POST(self):
        request = Request(self.factory.post('/'))
        mock_serializer = serializers.Serializer()
        mock_serializer.context = {'request': request}
        field = self.field_class()
        self._test_expected_dict(field)

    def test_get_attribute_request_GET(self):
        request = Request(self.factory.get('/'))
        mock_serializer = serializers.Serializer()
        mock_serializer.context = {'request': request}
        field = self.field_class()
        self._test_expected_dict(field)

    def test_get_attribute_request_GET_lang(self):
        """
        Pass a lang in the query string, expect to have a single string
        returned instead of an object.
        """
        # Note that we don't go through the middlewares etc so the actual
        # language for the process isn't changed, we don't care as
        # _expect_single_string() method simply tests with the current
        # language, whatever it is.
        request = Request(self.factory.get('/', {'lang': 'lol'}))
        assert request.GET['lang'] == 'lol'
        field = self.field_class()
        field.context = {'request': request}
        self._test_expected_single_string(field)

    def test_field_null(self):
        field = self.field_class()
        self.addon = Addon()

        field.bind('name', None)
        result = field.to_representation(field.get_attribute(self.addon))
        assert result is None

        field.bind('description', None)
        result = field.to_representation(field.get_attribute(self.addon))
        assert result is None


class TestESTranslationSerializerField(TestTranslationSerializerField):
    field_class = ESTranslationSerializerField

    def setUp(self):
        self.factory = APIRequestFactory()
        self.addon = Addon()
        self.addon.default_locale = 'en-US'
        self.addon.name_translations = {
            'en-US': u'English Name',
            'es': u'Spànish Name'
        }
        self.addon.description_translations = {
            'en-US': u'English Description',
            'fr': u'Frençh Description'
        }

    def test_attach_translations(self):
        data = {
            'foo_translations': [{
                'lang': 'testlang',
                'string': 'teststring'
            }, {
                'lang': 'testlang2',
                'string': 'teststring2'
            }]
        }
        self.addon = Addon()
        self.field_class().attach_translations(self.addon, data, 'foo')
        assert self.addon.foo_translations == {
            'testlang': 'teststring', 'testlang2': 'teststring2'}

    def test_attach_translations_target_name(self):
        data = {
            'foo_translations': [{
                'lang': 'testlang',
                'string': 'teststring'
            }, {
                'lang': 'testlang2',
                'string': 'teststring2'
            }]
        }

        self.addon = Addon()
        self.field_class().attach_translations(
            self.addon, data, 'foo', target_name='bar')
        assert self.addon.bar_translations, {
            'testlang': 'teststring', 'testlang2': 'teststring2'}

    def test_attach_translations_missing_key(self):
        data = {
            'foo_translations': None
        }
        self.addon = Addon()
        self.field_class().attach_translations(self.addon, data, 'foo')
        assert self.addon.foo_translations == {}

    def _test_expected_dict(self, field, serializer=None):
        field.bind('name', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = self.addon.name_translations
        assert result == expected

        field.source = None
        field.bind('description', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = self.addon.description_translations
        assert result == expected

    def _test_expected_single_string(self, field, serializer=None):
        field.bind('name', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = unicode(self.addon.name_translations['en-US'])
        assert result == expected

        field.source = None
        field.bind('description', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = unicode(self.addon.description_translations['en-US'])
        assert result == expected

    def test_get_attribute_source(self):
        self.addon.mymock = Mock()
        self.addon.mymock.mymocked_field = self.addon.name
        field = self.field_class(source='name')
        result = field.get_attribute(self.addon)
        expected = self.addon.name_translations
        assert result == expected

    def test_field_null(self):
        field = self.field_class()
        self.addon.name_translations = {}
        field.bind('name', None)
        result = field.to_representation(field.get_attribute(self.addon))
        assert result is None

        self.addon.description_translations = None
        field.bind('description', None)
        result = field.to_representation(field.get_attribute(self.addon))
        assert result is None
