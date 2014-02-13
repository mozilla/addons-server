# -*- coding: utf-8 -*-
from mock import Mock
from nose.tools import eq_, ok_
from rest_framework.request import Request
from rest_framework.serializers import CharField, Serializer
from rest_framework.test import APIRequestFactory
from test_utils import RequestFactory

import amo
from amo.tests import TestCase
from addons.models import AddonCategory, Category
from mkt.api.fields import (ESTranslationSerializerField, 
                            SlugOrPrimaryKeyRelatedField, SplitField,
                            TranslationSerializerField)
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp
from versions.models import Version
from translations.models import Translation


class _TestTranslationSerializerField(object):
    field_class = TranslationSerializerField

    def setUp(self):
        super(_TestTranslationSerializerField, self).setUp()
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
        field = self.field_class()
        result = field.from_native(data)
        eq_(result, data)

        data = {
            'fr': u'Non mais Allô quoi !',
            'en-US': u'No But Hello what!'
        }
        field = self.field_class()
        result = field.from_native(data)
        eq_(result, data)

        data = ['Bad Data']
        field = self.field_class()
        result = field.from_native(data)
        eq_(result, unicode(data))

    def test_field_from_native_strip(self):
        data = {
            'fr': u'  Non mais Allô quoi ! ',
            'en-US': u''
        }
        field = self.field_class()
        result = field.from_native(data)
        eq_(result, {'fr': u'Non mais Allô quoi !', 'en-US': u''})

    def test_field_to_native(self):
        field = self.field_class()
        self._test_expected_dict(field)

    def test_field_to_native_source(self):
        self.app.mymock = Mock()
        self.app.mymock.mymocked_field = self.app.name
        field = self.field_class(source='mymock.mymocked_field')
        result = field.field_to_native(self.app, 'shouldbeignored')
        expected = {
            'en-US': unicode(Translation.objects.get(id=self.app.name.id,
                                                     locale='en-US')),
            'es': unicode(Translation.objects.get(id=self.app.name.id,
                                                  locale='es')),
        }
        eq_(result, expected)

    def test_field_to_native_empty_context(self):
        mock_serializer = Serializer()
        mock_serializer.context = {}
        field = self.field_class()
        field.initialize(mock_serializer, 'name')
        self._test_expected_dict(field)

    def test_field_to_native_request_POST(self):
        request = Request(self.factory.post('/'))
        mock_serializer = Serializer()
        mock_serializer.context = {'request': request}
        field = self.field_class()
        field.initialize(mock_serializer, 'name')
        self._test_expected_dict(field)

    def test_field_to_native_request_GET(self):
        request = Request(self.factory.get('/'))
        mock_serializer = Serializer()
        mock_serializer.context = {'request': request}
        field = self.field_class()
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
        field = self.field_class()
        field.initialize(mock_serializer, 'name')
        self._test_expected_single_string(field)

    def test_field_null(self):
        field = self.field_class()
        self.app = Webapp()
        result = field.field_to_native(self.app, 'name')
        eq_(result, None)
        result = field.field_to_native(self.app, 'description')
        eq_(result, None)

class TestTranslationSerializerField(_TestTranslationSerializerField, TestCase):
    fixtures = fixture('user_2519', 'webapp_337141')


class TestESTranslationSerializerField(_TestTranslationSerializerField, TestCase):
    field_class = ESTranslationSerializerField

    def setUp(self):
        self.factory = APIRequestFactory()
        self.app = Webapp()
        self.app.default_locale = 'en-US'
        self.app.name_translations = {
            'en-US': u'English Name',
            'es': u'Spànish Name'
        }
        self.app.description_translations = {
            'en-US': u'English Description',
            'fr': u'Frençh Description'
        }

    def test_attach_translations(self):
        data = {
            'foo_translations' : [{
                'lang': 'testlang',
                'string': 'teststring'
            }, {
                'lang': 'testlang2',
                'string': 'teststring2'
            }]
        }
        self.app = Webapp()
        self.field_class().attach_translations(self.app, data, 'foo')
        eq_(self.app.foo_translations, {'testlang': 'teststring', 
                                        'testlang2': 'teststring2'})

    def test_attach_translations_target_name(self):
        data = {
            'foo_translations' : [{
                'lang': 'testlang',
                'string': 'teststring'
            }, {
                'lang': 'testlang2',
                'string': 'teststring2'
            }]
        }
        self.app = Webapp()
        self.field_class().attach_translations(self.app, data, 'foo',
            target_name='bar')
        eq_(self.app.bar_translations, {'testlang': 'teststring',
                                        'testlang2': 'teststring2'})

    def test_attach_translations_missing_key(self):
        data = {
            'foo_translations': None
        }
        self.app = Webapp()
        self.field_class().attach_translations(self.app, data, 'foo')
        eq_(self.app.foo_translations, {})

    def _test_expected_dict(self, field):
        result = field.field_to_native(self.app, 'name')
        expected = self.app.name_translations
        eq_(result, expected)

        result = field.field_to_native(self.app, 'description')
        expected = self.app.description_translations
        eq_(result, expected)

    def _test_expected_single_string(self, field):
        result = field.field_to_native(self.app, 'name')
        expected = unicode(self.app.name_translations['en-US'])
        eq_(result, expected)

        result = field.field_to_native(self.app, 'description')
        expected = unicode(self.app.description_translations['en-US'])
        eq_(result, expected)

    def test_field_to_native_source(self):
        self.app.mymock = Mock()
        self.app.mymock.mymockedfield_translations = self.app.name_translations
        field = self.field_class(source='mymock.mymockedfield')
        result = field.field_to_native(self.app, 'shouldbeignored')
        expected = self.app.name_translations
        eq_(result, expected)

    def test_field_null(self):
        field = self.field_class()
        self.app.name_translations = {}
        result = field.field_to_native(self.app, 'name')
        eq_(result, None)

        self.app.description_translations = None
        result = field.field_to_native(self.app, 'description')
        eq_(result, None)


class SlugOrPrimaryKeyRelatedFieldTests(TestCase):
    fixtures = fixture('webapp_337141')

    def test_render_as_pks(self):
        app = Webapp.objects.get(pk=337141)
        c1 = Category.objects.create(name='delicious', slug='foo',
                                     type=amo.ADDON_WEBAPP)
        c2 = Category.objects.create(name='scrumptious', slug='baz',
                                     type=amo.ADDON_WEBAPP)
        AddonCategory.objects.create(addon=app, category=c1)
        AddonCategory.objects.create(addon=app, category=c2)
        field = SlugOrPrimaryKeyRelatedField(queryset=Category.objects.all(),
                                             many=True)
        eq_(field.field_to_native(app, 'categories'), [c1.pk, c2.pk])

    def test_render_as_pk(self):
        v = Version.objects.get(pk=1268829)
        field = SlugOrPrimaryKeyRelatedField(queryset=Webapp.objects.all())
        eq_(field.field_to_native(v, 'addon'), v.addon.pk)

    def test_parse_as_pks(self):
        c1 = Category.objects.create(name='delicious', slug='foo',
                                     type=amo.ADDON_WEBAPP)
        c2 = Category.objects.create(name='scrumptious', slug='baz',
                                     type=amo.ADDON_WEBAPP)
        into = {}
        field = SlugOrPrimaryKeyRelatedField(queryset=Category.objects.all(),
                                             many=True)
        field.field_from_native({'categories': [c1.pk, c2.pk]}, None,
                                'categories', into)
        eq_(into, {'categories': [c1, c2]})

    def test_parse_as_pk(self):
        app = Webapp.objects.get(pk=337141)
        into = {}
        field = SlugOrPrimaryKeyRelatedField(queryset=Webapp.objects.all())
        field.field_from_native({'addon': 337141}, None, 'addon', into)
        eq_(into, {'addon': app})

    def test_render_as_slugs(self):
        app = Webapp.objects.get(pk=337141)
        c1 = Category.objects.create(name='delicious', slug='foo',
                                     type=amo.ADDON_WEBAPP)
        c2 = Category.objects.create(name='scrumptious', slug='baz',
                                     type=amo.ADDON_WEBAPP)
        AddonCategory.objects.create(addon=app, category=c1)
        AddonCategory.objects.create(addon=app, category=c2)
        field = SlugOrPrimaryKeyRelatedField(queryset=Category.objects.all(),
                                             render_as='slug',
                                             slug_field='slug',
                                             many=True)
        eq_(field.field_to_native(app, 'categories'), [c1.slug, c2.slug])

    def test_render_as_slug(self):
        v = Version.objects.get(pk=1268829)
        field = SlugOrPrimaryKeyRelatedField(queryset=Webapp.objects.all(),
                                             render_as='slug',
                                             slug_field='app_slug')
        eq_(field.field_to_native(v, 'addon'), v.addon.app_slug)

    def test_parse_as_slugs(self):
        c1 = Category.objects.create(name='delicious', slug='foo',
                                     type=amo.ADDON_WEBAPP)
        c2 = Category.objects.create(name='scrumptious', slug='baz',
                                     type=amo.ADDON_WEBAPP)
        into = {}
        field = SlugOrPrimaryKeyRelatedField(queryset=Category.objects.all(),
                                             many=True)
        field.field_from_native({'categories': [c1.slug, c2.slug]}, None,
                                'categories', into)
        eq_(into, {'categories': [c1, c2]})

    def test_parse_as_slug(self):
        app = Webapp.objects.get(pk=337141)
        into = {}
        field = SlugOrPrimaryKeyRelatedField(queryset=Webapp.objects.all(),
                                             slug_field='app_slug')
        field.field_from_native({'addon': app.app_slug}, None, 'addon', into)
        eq_(into, {'addon': app})


class Spud(object):
    pass


class Potato(object):
    def __init__(self, spud):
        self.spud = spud


class SpudSerializer(Serializer):
    pass


class PotatoSerializer(Serializer):
    spud = SplitField(CharField(), SpudSerializer())


class TestSplitField(TestCase):
    def setUp(self):
        self.request = RequestFactory().get('/')
        self.spud = Spud()
        self.potato = Potato(self.spud)
        self.serializer = PotatoSerializer(self.potato,
                                           context={'request': self.request})

    def test_initialize(self):
        """
        Test that the request context is passed from PotatoSerializer's context
        to the context of `PotatoSerializer.spud.output`.
        """
        field = self.serializer.fields['spud']
        eq_(self.request, field.output.context['request'],
            self.serializer.context['request'])
        ok_(not hasattr(field.input, 'context'))
