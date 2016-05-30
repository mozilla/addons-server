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
            'properties': {
                'max': {'type': 'long'},
                'min': {'type': 'long'},
                'max_human': {'type': 'string', 'index': 'no'},
                'min_human': {'type': 'string', 'index': 'no'},
            }
        }
        mapping = {
            doc_name: {
                'properties': {
                    'id': {'type': 'long'},

                    'app': {'type': 'long'},
                    'appversion': {'properties': {app.id: appver
                                                  for app in amo.APP_USAGE}},
                    'authors': {'type': 'string'},
                    'average_daily_users': {'type': 'long'},
                    'bayesian_rating': {'type': 'double'},
                    'category': {'type': 'integer'},
                    'created': {'type': 'date'},
                    'current_version': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'long', 'index': 'no'},
                            'reviewed': {'type': 'date', 'index': 'no'},
                            'files': {
                                'type': 'object',
                                'properties': {
                                    'id': {'type': 'long', 'index': 'no'},
                                    'created': {'type': 'date', 'index': 'no'},
                                    'hash': {'type': 'string', 'index': 'no'},
                                    'filename': {
                                        'type': 'string', 'index': 'no'},
                                    'platform': {
                                        'type': 'byte', 'index': 'no'},
                                    'size': {'type': 'long', 'index': 'no'},
                                    'status': {'type': 'byte'},
                                }
                            },
                            'version': {'type': 'string', 'index': 'no'},
                        }
                    },
                    'boost': {'type': 'float', 'null_value': 1.0},
                    'default_locale': {'type': 'string', 'index': 'no'},
                    'description': {'type': 'string', 'analyzer': 'snowball'},
                    'guid': {'type': 'string', 'index': 'no'},
                    'has_version': {'type': 'boolean'},
                    'has_theme_rereview': {'type': 'boolean'},
                    'hotness': {'type': 'double'},
                    'icon_type': {'type': 'string', 'index': 'no'},
                    'is_disabled': {'type': 'boolean'},
                    'is_listed': {'type': 'boolean'},
                    'last_updated': {'type': 'date'},
                    'modified': {'type': 'date', 'index': 'no'},
                    # Adding word-delimiter to split on camelcase and
                    # punctuation.
                    'name': {'type': 'string',
                             'analyzer': 'standardPlusWordDelimiter'},
                    # Turn off analysis on name so we can sort by it.
                    'name_sort': {'type': 'string', 'index': 'not_analyzed'},
                    'persona': {
                        'type': 'object',
                        'properties': {
                            'accentcolor': {'type': 'string', 'index': 'no'},
                            'author': {'type': 'string', 'index': 'no'},
                            'header': {'type': 'string', 'index': 'no'},
                            'footer': {'type': 'string', 'index': 'no'},
                            'is_new': {'type': 'boolean', 'index': 'no'},
                            'textcolor': {'type': 'string', 'index': 'no'},
                        }
                    },
                    'platforms': {'type': 'byte', 'index_name': 'platform'},
                    'public_stats': {'type': 'boolean'},
                    'slug': {'type': 'string'},
                    'status': {'type': 'byte'},
                    'summary': {'type': 'string', 'analyzer': 'snowball'},
                    'tags': {'type': 'string', 'index': 'not_analyzed',
                             'index_name': 'tag'},
                    'type': {'type': 'byte'},
                    'weekly_downloads': {'type': 'long'},
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
        attrs = ('id', 'average_daily_users', 'bayesian_rating', 'created',
                 'default_locale', 'guid', 'hotness', 'icon_type',
                 'is_disabled', 'is_listed', 'last_updated', 'modified',
                 'public_stats', 'slug', 'status', 'type', 'weekly_downloads')
        data = {attr: getattr(obj, attr) for attr in attrs}

        if obj.type == amo.ADDON_PERSONA:
            try:
                # Boost on popularity.
                data['boost'] = obj.persona.popularity ** .2
                data['has_theme_rereview'] = (
                    obj.persona.rereviewqueuetheme_set.exists())
                # 'weekly_downloads' field is used globally to sort, but
                # for themes weekly_downloads don't make much sense, use
                # popularity instead (FIXME: should be the other way around).
                data['weekly_downloads'] = obj.persona.popularity
                data['persona'] = {
                    'accentcolor': obj.persona.accentcolor,
                    'author': obj.persona.display_username,
                    'header': obj.persona.header,
                    'footer': obj.persona.footer,
                    'is_new': obj.persona.is_new(),
                    'textcolor': obj.persona.textcolor,
                }
            except ObjectDoesNotExist:
                # The instance won't have a persona while it's being created.
                pass
        else:
            # Boost by the number of users on a logarithmic scale. The maximum
            # boost (11,000,000 users for adblock) is about 5x.
            data['boost'] = obj.average_daily_users ** .2
            data['has_theme_rereview'] = None

        data['app'] = [app.id for app in obj.compatible_apps.keys()]
        data['appversion'] = {}
        for app, appver in obj.compatible_apps.items():
            if appver:
                min_, max_ = appver.min.version_int, appver.max.version_int
                min_human, max_human = appver.min.version, appver.max.version
            else:
                # Fake wide compatibility for search tools and personas.
                min_, max_ = 0, version_int('9999')
                min_human, max_human = None, None
            data['appversion'][app.id] = {
                'min': min_, 'min_human': min_human,
                'max': max_, 'max_human': max_human,
            }
        data['authors'] = [a.name for a in obj.listed_authors]
        # Quadruple the boost if the add-on is public.
        if obj.status == amo.STATUS_PUBLIC and 'boost' in data:
            data['boost'] = max(data['boost'], 1) * 4
        # We go through attach_categories and attach_tags transformer before
        # calling this function, it sets category_ids and tag_list.
        data['category'] = getattr(obj, 'category_ids', [])
        if obj.current_version:
            data['current_version'] = {
                'id': obj.current_version.pk,
                'files': [{
                    'id': file_.id,
                    'created': file_.created,
                    'filename': file_.filename,
                    'hash': file_.hash,
                    'platform': file_.platform,
                    'size': file_.size,
                    'status': file_.status,
                } for file_ in obj.current_version.all_files],
                'reviewed': obj.current_version.reviewed,
                'version': obj.current_version.version,
            }
            data['has_version'] = True
            data['platforms'] = [p.id for p in
                                 obj.current_version.supported_platforms]
        else:
            data['has_version'] = None
        data['tags'] = getattr(obj, 'tag_list', [])

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
