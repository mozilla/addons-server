import logging

from django.core.exceptions import ObjectDoesNotExist

from olympia import amo
from olympia.amo.indexers import BaseSearchIndexer
from olympia.versions.compare import version_int


log = logging.getLogger('z.es')


class AddonIndexer(BaseSearchIndexer):
    @classmethod
    def get_model(cls):
        from olympia.addons.models import Addon
        return Addon

    @classmethod
    def get_mapping(cls):
        doc_name = cls.get_doctype_name()
        appver = {
            'dynamic': False,
            'properties': {
                'max': {'type': 'long'},
                'min': {'type': 'long'},
            }
        }
        mapping = {
            doc_name: {
                'properties': {
                    'boost': {'type': 'float', 'null_value': 1.0},
                    'default_locale': {'type': 'string', 'index': 'no'},
                    'last_updated': {'type': 'date'},
                    # Turn off analysis on name so we can sort by it.
                    'name_sort': {'type': 'string', 'index': 'not_analyzed'},
                    # Adding word-delimiter to split on camelcase and
                    # punctuation.
                    'name': {'type': 'string',
                             'analyzer': 'standardPlusWordDelimiter'},
                    'summary': {'type': 'string', 'analyzer': 'snowball'},
                    'description': {'type': 'string', 'analyzer': 'snowball'},
                    'tags': {'type': 'string', 'index': 'not_analyzed',
                             'index_name': 'tag'},
                    'platforms': {'type': 'integer', 'index_name': 'platform'},
                    'appversion': {'properties': {app.id: appver
                                                  for app in amo.APP_USAGE}},
                },
            },
        }

        # Add fields that we expect to return all translations without being
        # analyzed/indexed.
        cls.attach_translation_mappings(
            mapping, ('description', 'homepage', 'name', 'summary',
                      'support_email', 'support_url'))

        # Add language-specific analyzers for localized fields that are
        # analyzed/indexed.
        cls.attach_language_specific_analyzers(
            mapping, ('name', 'description', 'summary'))

        return mapping

    @classmethod
    def extract_document(cls, obj):
        """Extract indexable attributes from an add-on."""
        attrs = ('id', 'slug', 'created', 'default_locale', 'last_updated',
                 'weekly_downloads', 'bayesian_rating', 'average_daily_users',
                 'status', 'type', 'hotness', 'is_disabled', 'is_listed')
        data = {attr: getattr(obj, attr) for attr in attrs}
        data['authors'] = [a.name for a in obj.listed_authors]
        # We go through attach_categories and attach_tags transformer before
        # calling this function, it sets category_ids and tag_list.
        data['category'] = getattr(obj, 'category_ids', [])
        data['tags'] = getattr(obj, 'tag_list', [])
        if obj.current_version:
            data['platforms'] = [p.id for p in
                                 obj.current_version.supported_platforms]
        data['appversion'] = {}
        for app, appver in obj.compatible_apps.items():
            if appver:
                min_, max_ = appver.min.version_int, appver.max.version_int
            else:
                # Fake wide compatibility for search tools and personas.
                min_, max_ = 0, version_int('9999')
            data['appversion'][app.id] = dict(min=min_, max=max_)
        try:
            data['has_version'] = obj._current_version is not None
        except ObjectDoesNotExist:
            data['has_version'] = None
        data['app'] = [app.id for app in obj.compatible_apps.keys()]

        if obj.type == amo.ADDON_PERSONA:
            try:
                # This would otherwise get attached by the transformer.
                data['weekly_downloads'] = obj.persona.popularity
                # Boost on popularity.
                data['boost'] = obj.persona.popularity ** .2
                data['has_theme_rereview'] = (
                    obj.persona.rereviewqueuetheme_set.exists())
            except ObjectDoesNotExist:
                # The instance won't have a persona while it's being created.
                pass
        else:
            # Boost by the number of users on a logarithmic scale. The maximum
            # boost (11,000,000 users for adblock) is about 5x.
            data['boost'] = obj.average_daily_users ** .2
        # Double the boost if the add-on is public.
        if obj.status == amo.STATUS_PUBLIC and 'boost' in data:
            data['boost'] = max(data['boost'], 1) * 4

        # Handle localized fields.
        # First, deal with the 3 fields that need everything:
        for field in ('description', 'name', 'summary'):
            data.update(cls.extract_field_raw_translations(obj, field))
            data.update(cls.extract_field_search_translations(obj, field))
            data.update(cls.extract_field_analyzed_translations(obj, field))

        # Then add fields that only need to be returned to the API without
        # contributing to search relevancy.
        for field in ('homepage', 'support_email', 'support_url'):
            data.update(cls.extract_field_raw_translations(obj, field))

        # Finally, add the special sort field, coercing the current translation
        # into an unicode object first.
        data['name_sort'] = unicode(obj.name).lower()

        return data
