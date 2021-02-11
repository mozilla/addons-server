# -*- coding: utf-8 -*-
from django.core.exceptions import ValidationError
from django.test.utils import override_settings

import pytest
from unittest.mock import Mock
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from olympia.addons.models import Addon
from olympia.addons.serializers import AddonSerializer
from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.api.fields import (
    ESTranslationSerializerField,
    GetTextTranslationSerializerField,
    GetTextTranslationSerializerFieldFlat,
    FallbackField,
    ReverseChoiceField,
    SlugOrPrimaryKeyRelatedField,
    SplitField,
    TranslationSerializerField,
    TranslationSerializerFieldFlat,
)
from olympia.translations.models import Translation
from olympia.versions.models import Version


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
        self.addon = addon_factory(description='Descrîption...')
        Translation.objects.create(
            id=self.addon.name.id, locale='es', localized_string='Name in Español'
        )

    def _test_expected_dict(self, field, serializer=None):
        field.bind('name', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = {
            'en-US': str(
                Translation.objects.get(id=self.addon.name.id, locale='en-US')
            ),
            'es': str(Translation.objects.get(id=self.addon.name.id, locale='es')),
        }
        assert result == expected

        field.source = None
        field.bind('description', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = {
            'en-US': Translation.objects.get(
                id=self.addon.description.id, locale='en-US'
            ),
        }
        assert result == expected

    def _test_expected_single_locale(self, field, serializer=None):
        field.bind('name', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = {'es': 'Name in Español'}
        assert result == expected

        field.source = None
        field.bind('description', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = {
            'en-US': str(self.addon.description),
            'es': None,
            '_default': 'en-US',
        }
        # We need the order to be exactly the same
        assert list(result.items()) == list(expected.items())
        assert list(result)[0] == 'en-US'

    def test_to_representation(self):
        data = 'Translatiön'
        field = self.field_class()
        result = field.to_representation(data)
        assert result == data

    def test_to_representation_dict(self):
        data = {'fr': 'Non mais Allô quoi !', 'en-US': 'No But Hello what!'}
        field = self.field_class()
        result = field.to_representation(data)
        assert result == data

    def test_to_internal_value(self):
        data = {'fr': 'Non mais Allô quoi !', 'en-US': 'No But Hello what!'}
        field = self.field_class()
        # Multiple translations
        result = field.to_internal_value(data)
        assert result == data
        # Single translation
        data.pop('en-US')
        assert len(data) == 1
        result = field.to_internal_value(data)
        assert result == data
        # A flat string value is forbidden now
        with self.assertRaises(ValidationError) as exc:
            field.to_internal_value(data['fr'])
        assert exc.exception.message == (
            'You must provide an object of {lang-code:value}.'
        )

    def test_to_internal_value_strip(self):
        data = {'fr': '  Non mais Allô quoi ! ', 'en-US': ''}
        field = self.field_class()
        result = field.to_internal_value(data)
        assert result == {'fr': 'Non mais Allô quoi !', 'en-US': ''}

    def test_wrong_locale_code(self):
        data = {
            'unknown-locale': 'some name',
        }
        field = self.field_class()
        with self.assertRaises(ValidationError) as exc:
            field.to_internal_value(data)
        assert exc.exception.message == (
            "The language code 'unknown-locale' is invalid."
        )

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
        result = field.get_attribute(self.addon)
        expected = {
            'en-US': str(
                Translation.objects.get(id=self.addon.name.id, locale='en-US')
            ),
            'es': str(Translation.objects.get(id=self.addon.name.id, locale='es')),
        }
        assert result == expected

    def test_get_attribute_source_missing_parent_object(self):
        self.addon.mymock = None
        field = self.field_class(source='mymock.mymocked_field')
        result = field.get_attribute(self.addon)
        assert result is None

    def test_get_attribute_empty_context(self):
        mock_serializer = serializers.Serializer(context={})
        field = self.field_class()
        self._test_expected_dict(field, mock_serializer)

    def test_field_get_attribute_request_POST(self):
        request = Request(self.factory.post('/'))
        mock_serializer = serializers.Serializer(context={'request': request})
        field = self.field_class()
        self._test_expected_dict(field, mock_serializer)

    def test_get_attribute_request_GET(self):
        request = Request(self.factory.get('/'))
        mock_serializer = serializers.Serializer(context={'request': request})
        field = self.field_class()
        self._test_expected_dict(field, mock_serializer)

    def test_get_attribute_request_GET_lang(self):
        """
        Pass a lang in the query string, expect to have a single string
        returned instead of an object.
        """
        # We don't go through the middlewares etc where the language for the
        # process would be set, so we have to manually activate the correct
        # locale.
        request = Request(self.factory.get('/', {'lang': 'es'}))
        assert request.GET['lang'] == 'es'
        mock_serializer = serializers.Serializer(context={'request': request})
        with self.activate('es'):
            if self.addon.id:
                # Reload so the transformer loads the translation in the
                # correct locale.
                # (But only if it's in the database - the ES test doesn't save)
                self.addon = self.addon.reload()
            field = self.field_class()
            self._test_expected_single_locale(field, mock_serializer)

    def test_field_null(self):
        field = self.field_class()
        self.addon = Addon()

        field.bind('name', None)
        result = field.to_representation(field.get_attribute(self.addon))
        assert result is None

        field.bind('description', None)
        result = field.to_representation(field.get_attribute(self.addon))
        assert result is None

    def test_field_value_null(self):
        self.addon = addon_factory(slug='lol', name=None, description=None)

        request = Request(self.factory.get('/', {'lang': 'en-US'}))
        mock_serializer = serializers.Serializer(context={'request': request})
        field = self.field_class()

        field.bind('name', mock_serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        assert result is None

        field.source = None
        field.bind('description', mock_serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        assert result is None


@override_settings(DRF_API_GATES={None: ('l10n_flat_input_output',)})
class TestTranslationSerializerFieldFlat(TestTranslationSerializerField):
    def _test_expected_single_locale(self, field, serializer=None):
        field.bind('name', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = str(self.addon.name)
        assert result == expected

        field.source = None
        field.bind('description', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = str(self.addon.description)
        assert result == expected

    def test_to_internal_value(self):
        data = {'fr': 'Non mais Allô quoi !', 'en-US': 'No But Hello what!'}
        field = self.field_class()
        # Multiple translations
        result = field.to_internal_value(data)
        assert result == data
        # Single translation
        result = field.to_internal_value(data['fr'])
        assert result == data['fr']


class TestESTranslationSerializerField(TestTranslationSerializerField):
    field_class = ESTranslationSerializerField

    def setUp(self):
        self.factory = APIRequestFactory()
        self.addon = Addon()
        self.addon.default_locale = 'en-US'
        self.addon.name_translations = {
            'en-US': 'English Name',
            'es': 'Name in Español',
        }
        self.addon.description_translations = {
            'en-US': 'English Description',
            'fr': 'Frençh Description',
        }

    def test_attach_translations(self):
        data = {
            'foo_translations': [
                {'lang': 'en-US', 'string': 'teststring'},
                {'lang': 'es', 'string': 'teststring-es'},
            ]
        }
        self.addon = Addon()
        self.field_class().attach_translations(self.addon, data, 'foo')
        assert self.addon.foo_translations == {
            'en-US': 'teststring',
            'es': 'teststring-es',
        }

    def test_attach_translations_target_name(self):
        data = {
            'foo_translations': [
                {'lang': 'en-US', 'string': 'teststring'},
                {'lang': 'es', 'string': 'teststring-es'},
            ]
        }

        self.addon = Addon()
        with self.activate('es'):
            self.field_class().attach_translations(
                self.addon, data, 'foo', target_name='bar'
            )
        assert self.addon.bar_translations, {
            'en-US': 'teststring',
            'es': 'teststring-es',
        }
        assert self.addon.bar.localized_string == 'teststring-es'

    def test_attach_translations_missing_key(self):
        data = {'foo_translations': None}
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

    def _test_expected_single_locale(self, field, serializer=None):
        field.bind('name', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = {
            'es': str(self.addon.name_translations['es']),
        }
        assert result == expected

        field.source = None
        field.bind('description', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = {
            'en-US': str(self.addon.description_translations['en-US']),
            'es': None,
            '_default': 'en-US',
        }
        # We need the order to be exactly the same
        assert list(result.items()) == list(expected.items())
        assert list(result)[0] == 'en-US'

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

    def test_field_value_null(self):
        request = Request(self.factory.get('/', {'lang': 'en-US'}))
        mock_serializer = serializers.Serializer(context={'request': request})

        field = self.field_class()
        self.addon.description_translations = {'en-US': None}
        field.bind('description', mock_serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        assert result is None


@override_settings(DRF_API_GATES={None: ('l10n_flat_input_output',)})
class TestESTranslationSerializerFieldFlat(
    TestTranslationSerializerFieldFlat, TestESTranslationSerializerField
):
    def _test_expected_single_locale(self, field, serializer=None):
        field.bind('name', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = str(self.addon.name_translations['es'])
        assert result == expected

        field.source = None
        field.bind('description', serializer)
        result = field.to_representation(field.get_attribute(self.addon))
        expected = str(self.addon.description_translations['en-US'])
        assert result == expected


class TestSlugOrPrimaryKeyRelatedField(TestCase):
    def setUp(self):
        self.addon = addon_factory()

    def test_render_as_pk(self):
        obj = Mock()
        obj.attached = self.addon

        field = SlugOrPrimaryKeyRelatedField(read_only=True)
        field.bind('attached', None)
        assert field.to_representation(field.get_attribute(obj)) == self.addon.pk

    def test_render_as_pks_many(self):
        obj = Mock()
        obj.attached = [self.addon]

        field = SlugOrPrimaryKeyRelatedField(many=True, read_only=True)
        field.bind('attached', None)
        assert field.to_representation(field.get_attribute(obj)) == [self.addon.pk]

    def test_render_as_slug(self):
        obj = Mock()
        obj.attached = self.addon

        field = SlugOrPrimaryKeyRelatedField(render_as='slug', read_only=True)
        field.bind('attached', None)
        assert field.to_representation(field.get_attribute(obj)) == self.addon.slug

    def test_render_as_slugs_many(self):
        obj = Mock()
        obj.attached = [self.addon]

        field = SlugOrPrimaryKeyRelatedField(
            render_as='slug', many=True, read_only=True
        )
        field.bind('attached', None)
        assert field.to_representation(field.get_attribute(obj)) == [self.addon.slug]

    def test_parse_as_pk(self):
        field = SlugOrPrimaryKeyRelatedField(queryset=Addon.objects.all())
        assert field.to_internal_value(self.addon.pk) == self.addon

    def test_parse_as_pks_many(self):
        addon2 = addon_factory()
        field = SlugOrPrimaryKeyRelatedField(queryset=Addon.objects.all(), many=True)
        assert field.to_internal_value([self.addon.pk, addon2.pk]) == [
            self.addon,
            addon2,
        ]

    def test_parse_as_slug(self):
        field = SlugOrPrimaryKeyRelatedField(queryset=Addon.objects.all())
        assert field.to_internal_value(self.addon.slug) == self.addon

    def test_parse_as_slugs_many(self):
        addon2 = addon_factory()
        field = SlugOrPrimaryKeyRelatedField(queryset=Addon.objects.all(), many=True)
        assert field.to_internal_value([self.addon.slug, addon2.slug]) == [
            self.addon,
            addon2,
        ]


class SampleSplitFieldSerializer(serializers.Serializer):
    addon = SplitField(
        serializers.PrimaryKeyRelatedField(queryset=Addon.objects), AddonSerializer()
    )


class TestSplitField(TestCase):
    def setUp(self):
        self.addon = addon_factory()

    def test_output(self):
        # If we pass an Addon instance.
        serializer = SampleSplitFieldSerializer({'addon': self.addon})
        assert 'addon' in serializer.data
        # The output is from AddonSerializer.
        assert serializer.data['addon']['id'] == self.addon.id
        assert serializer.data['addon']['slug'] == self.addon.slug

    def test_input(self):
        # If we pass data (e.g. on create) the input serializer is used.
        data = {'addon': self.addon.id}
        serializer = SampleSplitFieldSerializer(data=data)
        assert serializer.is_valid()
        assert serializer.to_internal_value(data=data) == {'addon': self.addon}


class Thing:
    pass


class SampleGetTextSerializer(serializers.Serializer):
    desc = GetTextTranslationSerializerField()


@pytest.mark.needs_locales_compilation
class TestGetTextTranslationSerializerField(TestCase):
    desc_en = (
        # this is predefined in strings.jinja2 (and localized already)
        'Block invisible trackers and spying ads that follow you around the web.'
    )
    desc_fr = (
        'Bloquez les traqueurs invisibles et les publicités espionnes qui vous '
        'suivent sur le Web.'
    )
    desc_de = (
        'Blockieren Sie unsichtbare Verfolger und Werbung, die Sie beobachtet '
        'und im Netz verfolgt.'
    )

    def serialize(self, item, lang=None):
        request = APIRequestFactory().get('/' if not lang else f'/?lang={lang}')
        request.version = 'v5'
        return SampleGetTextSerializer(context={'request': request}).to_representation(
            item
        )

    def test_no_lang(self):
        thing = Thing()
        thing.desc = self.desc_en
        thing.default_locale = 'de'

        assert self.serialize(thing)['desc'] == {
            'en-US': self.desc_en,
            'de': self.desc_de,
        }

        # repeat for the edge case when we have a different system language than en-US
        with self.activate('fr'):
            assert self.serialize(thing)['desc'] == {
                'en-US': self.desc_en,
                'fr': self.desc_fr,
                'de': self.desc_de,
            }

    def test_lang_specified(self):
        thing = Thing()
        thing.desc = self.desc_en
        thing.default_locale = 'de'

        # we have l10n for fr
        with self.activate('fr'):
            assert self.serialize(thing, 'fr')['desc'] == {
                'fr': self.desc_fr,
            }

        # but we don't for az
        with self.activate('az'):
            assert self.serialize(thing, 'az')['desc'] == {
                'de': self.desc_de,
                'az': None,
                '_default': 'de',
            }

            # cover the edge case where the object has a default locale we don't have
            thing.default_locale = 'az'
            assert self.serialize(thing, 'az')['desc'] == {
                'en-US': self.desc_en,
                'az': None,
                '_default': 'en-US',
            }


class SampleFlatTranslationSerializer(serializers.ModelSerializer):
    gettext = GetTextTranslationSerializerFieldFlat(source='approval_notes')
    db = TranslationSerializerFieldFlat(source='release_notes')

    class Meta:
        model = Version
        fields = [
            'gettext',
            'db',
        ]


class TestFlatTranslationSerializerFields(TestCase):
    desc_en = (
        # this is predefined in strings.jinja2 (and localized already)
        'Block invisible trackers and spying ads that follow you around the web.'
    )
    desc_fr = (
        'Bloquez les traqueurs invisibles et les publicités espionnes qui vous '
        'suivent sur le Web.'
    )

    def serialize(self, item, lang=None):
        request = APIRequestFactory().get('/' if not lang else f'/?lang={lang}')
        request.version = 'v5'
        return SampleFlatTranslationSerializer(
            context={'request': request}).to_representation(item)

    @pytest.mark.needs_locales_compilation
    def test_basic(self):
        version = version_factory(
            addon=addon_factory(),
            approval_notes=self.desc_en,
            release_notes={'en-US': 'release!', 'fr': 'lé release!'})
        assert self.serialize(version) == {
            'gettext': {'en-US': self.desc_en},
            'db': {'en-US': 'release!', 'fr': 'lé release!'},
        }
        with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
            assert self.serialize(version) == {
                'gettext': self.desc_en,
                'db': 'release!',
            }

        # And works when a lang is specified:
        with self.activate('fr'):
            version.reload()
            assert self.serialize(version, 'fr') == {
                'gettext': {'fr': self.desc_fr},
                'db': {'fr': 'lé release!'},
            }
            with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
                assert self.serialize(version) == {
                    'gettext': self.desc_fr,
                    'db': 'lé release!',
                }

        # Test the empty string case
        version.approval_notes = ''
        version.release_notes = ''
        version.save()
        assert self.serialize(version) == {
            'gettext': None,
            'db': None,
        }
        with override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)}):
            assert self.serialize(version) == {
                'gettext': '',
                'db': '',
            }


class SampleFallbackFieldSerializer(serializers.ModelSerializer):
    name = FallbackField(
        serializers.CharField(),
        serializers.CharField(source='description'),
        serializers.CharField(source='summary'),
    )

    class Meta:
        model = Addon
        fields = [
            'name',
        ]


class TestFallbackField(TestCase):
    def test_output(self):
        addon = addon_factory(name='náme', description='déscription', summary='summáry')

        # if the addon name is set then we get name
        assert SampleFallbackFieldSerializer(addon).data['name'] == addon.name

        # if it's not set we should get the description
        addon.update(name='')
        assert SampleFallbackFieldSerializer(addon).data['name'] == addon.description

        # and if description isn't set either, then the 3rd field
        addon.update(description='')
        assert SampleFallbackFieldSerializer(addon).data['name'] == addon.summary

    def test_input(self):
        # If we pass data (e.g. on create) the first serializer is used.
        data = {'name': 'foobar'}
        serializer = SampleFallbackFieldSerializer(data=data)
        assert serializer.is_valid()
        assert serializer.to_internal_value(data=data) == {'name': 'foobar'}
        serializer.save()
        assert Addon.objects.count() == 1
        addon = Addon.objects.get()
        assert addon.name == 'foobar'
        assert addon.description is None
        assert addon.summary is None

        serializer = SampleFallbackFieldSerializer(instance=addon, data={'name': 'ho!'})
        assert serializer.is_valid()
        serializer.save()
        assert Addon.objects.count() == 1  # still one
        addon.reload()
        assert addon.name == 'ho!'  # updated
        assert addon.description is None
        assert addon.summary is None
