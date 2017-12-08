# -*- coding: utf-8 -*-
from olympia.amo.tests import TestCase
from olympia.bandwagon.indexers import CollectionIndexer
from olympia.bandwagon.models import Collection
from olympia.bandwagon.tasks import attach_translations
from olympia.constants.applications import FIREFOX


class TestCollectionIndexer(TestCase):
    def setUp(self):
        super(TestCollectionIndexer, self).setUp()
        self.attrs = ('author_username', 'created', 'id', 'listed', 'modified',
                      'monthly_subscribers', 'rating', 'slug', 'subscribers',
                      'type', 'weekly_subscribers')
        self.collection = Collection.objects.create(
            application=FIREFOX.id, monthly_subscribers=666, rating=4,
            subscribers=999, weekly_subscribers=133,)
        self.indexer = CollectionIndexer()

    def _extract(self):
        qs = Collection.objects.filter(id__in=[self.collection.pk])
        for t in (attach_translations,):
            qs = qs.transform(t)
        self.collection = list(qs)[0]
        return self.indexer.extract_document(self.collection)

    def test_extract_attributes(self):
        extracted = self._extract()
        for attr in self.attrs:
            assert extracted[attr] == getattr(self.collection, attr)
        # 'application' is renamed to 'app' in the extraction.
        assert extracted['app'] == self.collection.application

    def test_extract_language_specific(self):
        translations_name = {
            'en-US': u'CName in ënglish',
            'es': u'CName in Español',
            'it': None,
        }
        translations_desc = {
            'en-US': u'Collection Description in ënglish',
            'es': u'Collection Description in Español',
            'fr': '',
        }
        self.collection.name = translations_name
        self.collection.description = translations_desc
        self.collection.save()

        extracted = self._extract()
        assert extracted['name_l10n_english'] == [translations_name['en-US']]
        assert extracted['name_l10n_french'] == []
        assert extracted['name_l10n_italian'] == []
        assert extracted['name_l10n_spanish'] == [translations_name['es']]

        assert extracted['description_l10n_english'] == [
            translations_desc['en-US']]
        assert extracted['description_l10n_french'] == ['']
        assert extracted['description_l10n_italian'] == []
        assert extracted['description_l10n_spanish'] == [
            translations_desc['es']]

    def test_mapping(self):
        doc_name = self.indexer.get_doctype_name()
        assert doc_name

        mapping_properties = self.indexer.get_mapping()[doc_name]['properties']

        # Spot check: make sure addon-specific 'summary' field is not present.
        assert 'summary' not in mapping_properties

        # Make sure 'boost' is present.
        assert 'boost' in mapping_properties

        # Make sure the name & description translated properties are present.
        assert 'description_l10n_spanish' in mapping_properties
        assert 'name_l10n_french' in mapping_properties
