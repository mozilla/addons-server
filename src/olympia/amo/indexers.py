from django.conf import settings

import olympia.core.logger

from olympia.constants.search import SEARCH_ANALYZER_MAP

from .models import SearchMixin
from .utils import to_language


class BaseSearchIndexer(object):
    """
    Base Indexer class for all search-related things (as opposed to
    stats-related things).

    Intended to be inherited from every document type that we want to put in
    ElasticSearch for search-related purposes. A class inheriting from
    BaseSearchIndexer should implement the following classmethods:

    - get_model(cls)
    - get_mapping(cls)
    - extract_document(cls, obj)
    """

    @classmethod
    def get_index_alias(cls):
        """Return the index alias name."""
        return settings.ES_INDEXES.get(SearchMixin.ES_ALIAS_KEY)

    @classmethod
    def get_doctype_name(cls):
        """Return the document type name for this indexer. We default to simply
        use the db table from the corresponding model."""
        return cls.get_model()._meta.db_table

    @classmethod
    def attach_translation_mappings(cls, mapping, field_names):
        """
        For each field in field_names, attach a dict to the ES mapping
        properties making "<field_name>_translations" an object containing
        "string" and "lang" as non-indexed strings.

        Used to store non-indexed, non-analyzed translations in ES that will be
        sent back by the API for each item. It does not take care of the
        indexed content for search, it's there only to store and return
        raw translations.
        """
        doc_name = cls.get_doctype_name()

        for field_name in field_names:
            # _translations is the suffix in TranslationSerializer.
            mapping[doc_name]['properties'].update({
                '%s_translations' % field_name: {
                    'type': 'object',
                    'properties': {
                        'lang': {'type': 'text', 'index': False},
                        'string': {'type': 'text', 'index': False}
                    }
                }
            })

    @classmethod
    def attach_language_specific_analyzers(cls, mapping, field_names):
        """
        For each field in field_names, attach language-specific mappings that
        will use specific analyzers for these fields in every language that we
        support.

        These mappings are used by the search filtering code if they exist.
        """
        doc_name = cls.get_doctype_name()

        for analyzer in SEARCH_ANALYZER_MAP:
            for field in field_names:
                property_name = '%s_l10n_%s' % (field, analyzer)
                mapping[doc_name]['properties'][property_name] = {
                    'type': 'text',
                    'analyzer': analyzer,
                }

    @classmethod
    def extract_field_raw_translations(cls, obj, field, db_field=None):
        """
        Returns a dict containing raw translations that we need to store for
        the API.
        """
        if db_field is None:
            db_field = '%s_id' % field

        extend_with_me = {
            '%s_translations' % field: [
                {'lang': to_language(lang), 'string': string}
                for lang, string in obj.translations[getattr(obj, db_field)]
                if string
            ]
        }
        return extend_with_me

    @classmethod
    def extract_field_search_translations(cls, obj, field, db_field=None):
        """
        Returns a dict containing all translations for the field, that will be
        analyzed and indexed by ES *without* language-specific analyzers.
        """
        if db_field is None:
            db_field = '%s_id' % field

        extend_with_me = {
            field: list(
                set(s for _, s in obj.translations[getattr(obj, db_field)]))
        }
        return extend_with_me

    @classmethod
    def extract_field_analyzed_translations(cls, obj, field, db_field=None):
        """
        Returns a dict containing translations for each language-specific
        analyzer for the given field.
        """
        if db_field is None:
            db_field = '%s_id' % field

        extend_with_me = {}

        # Indices for each language. languages is a list of locales we want to
        # index with analyzer if the string's locale matches.
        for analyzer, languages in SEARCH_ANALYZER_MAP.iteritems():
            extend_with_me['%s_l10n_%s' % (field, analyzer)] = list(
                set(string for locale, string
                    in obj.translations[getattr(obj, db_field)]
                    if locale.lower() in languages))

        return extend_with_me
