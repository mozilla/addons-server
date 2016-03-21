# -*- coding: utf-8 -*-
from olympia.amo.tests import TestCase
from olympia.addons.models import (
    Addon, attach_categories, attach_tags, attach_translations)
from olympia.addons.indexers import AddonIndexer


class TestAddonIndexer(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestAddonIndexer, self).setUp()
        self.attrs = (
            'id', 'slug', 'created', 'default_locale', 'last_updated',
            'weekly_downloads', 'average_daily_users', 'status', 'type',
            'hotness', 'is_disabled', 'is_listed',
        )
        self.transforms = (attach_categories, attach_tags, attach_translations)
        self.indexer = AddonIndexer()

    def _extract(self):
        qs = Addon.objects.filter(id__in=[3615])
        for t in self.transforms:
            qs = qs.transform(t)
        self.addon = list(qs)[0]
        return self.indexer.extract_document(self.addon)

    def test_extract_attributes(self):
        extracted = self._extract()
        for attr in self.attrs:
            assert extracted[attr] == getattr(self.addon, attr)

    def test_extract_translations(self):
        translations_name = {
            'en-US': u'Name in ënglish',
            'es': u'Name in Español',
            'it': None,  # Empty name should be ignored in extract.
        }
        translations_description = {
            'en-US': u'Description in ënglish',
            'es': u'Description in Español',
            'fr': '',  # Empty description should be ignored in extract.
        }
        self.addon = Addon.objects.get(pk=3615)
        self.addon.name = translations_name
        self.addon.description = translations_description
        self.addon.save()
        extracted = self._extract()
        assert extracted['name_translations'] == [
            {'lang': u'en-US', 'string': translations_name['en-US']},
            {'lang': u'es', 'string': translations_name['es']},
        ]
        assert extracted['description_translations'] == [
            {'lang': u'en-US', 'string': translations_description['en-US']},
            {'lang': u'es', 'string': translations_description['es']},
        ]

    def test_mapping(self):
        doc_name = self.indexer.get_doctype_name()
        assert doc_name

        mapping_properties = self.indexer.get_mapping()[doc_name]['properties']

        # Make sure a few key fields are present.
        assert 'boost' in mapping_properties
        assert 'description' in mapping_properties
        assert 'name' in mapping_properties
        assert 'summary' in mapping_properties
        assert 'default_locale' in mapping_properties

        # Make sure the translated fields analyzed properties are present.
        assert 'description_spanish' in mapping_properties
        assert 'name_french' in mapping_properties
        assert 'summary_french' in mapping_properties

        # Make sure those analyzed properties are not used for fields which
        # don't need it.
        assert 'homepage_french' not in mapping_properties
        assert 'support_email_french' not in mapping_properties
        assert 'support_url_french' not in mapping_properties
        assert 'homepage' not in mapping_properties
        assert 'support_email' not in mapping_properties
        assert 'support_url' not in mapping_properties

        # Make sure the translated fields raw fields for the API are present.
        assert 'description_translations' in mapping_properties
        assert 'homepage_translations' in mapping_properties
        assert 'name_translations' in mapping_properties
        assert 'summary_translations' in mapping_properties
        assert 'support_email_translations' in mapping_properties
        assert 'support_url_translations' in mapping_properties

        # Make sure default_locale and translated fields are not indexed.
        assert mapping_properties['default_locale']['index'] == 'no'
        name_translations = mapping_properties['name_translations']
        assert name_translations['properties']['lang']['index'] == 'no'
        assert name_translations['properties']['string']['index'] == 'no'
