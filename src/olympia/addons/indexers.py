from django.core.exceptions import ObjectDoesNotExist

import olympia.core.logger
from olympia import amo
from olympia.amo.indexers import BaseSearchIndexer
from olympia.amo.utils import attach_trans_dict
from olympia.versions.compare import version_int


log = olympia.core.logger.getLogger('z.es')


class AddonIndexer(BaseSearchIndexer):
    @classmethod
    def get_model(cls):
        from olympia.addons.models import Addon
        return Addon

    @classmethod
    def get_mapping(cls):
        doc_name = cls.get_doctype_name()
        appver_mapping = {
            'properties': {
                'max': {'type': 'long'},
                'min': {'type': 'long'},
                'max_human': {'type': 'string', 'index': 'no'},
                'min_human': {'type': 'string', 'index': 'no'},
            }
        }
        version_mapping = {
            'type': 'object',
            'properties': {
                'compatible_apps': {'properties': {app.id: appver_mapping
                                                   for app in amo.APP_USAGE}},
                # Keep '<version>.id' indexed to be able to run exists queries
                # on it.
                'id': {'type': 'long'},
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
                        'webext_permissions_list': {
                            'type': 'string', 'index': 'no'},
                    }
                },
                'version': {'type': 'string', 'index': 'no'},
            }
        }
        mapping = {
            doc_name: {
                'properties': {
                    'id': {'type': 'long'},

                    'app': {'type': 'byte'},
                    'average_daily_users': {'type': 'long'},
                    'bayesian_rating': {'type': 'double'},
                    'current_beta_version': version_mapping,
                    'category': {'type': 'integer'},
                    'created': {'type': 'date'},
                    'current_version': version_mapping,
                    'boost': {'type': 'float', 'null_value': 1.0},
                    'default_locale': {'type': 'string', 'index': 'no'},
                    'description': {'type': 'string', 'analyzer': 'snowball'},
                    'guid': {'type': 'string', 'index': 'no'},
                    'has_eula': {'type': 'boolean', 'index': 'no'},
                    'has_privacy_policy': {'type': 'boolean', 'index': 'no'},
                    'has_theme_rereview': {'type': 'boolean'},
                    'hotness': {'type': 'double'},
                    'icon_type': {'type': 'string', 'index': 'no'},
                    'is_disabled': {'type': 'boolean'},
                    'is_experimental': {'type': 'boolean'},
                    'last_updated': {'type': 'date'},
                    'latest_unlisted_version': version_mapping,
                    'listed_authors': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'long', 'index': 'no'},
                            'name': {'type': 'string'},
                            'username': {'type': 'string', 'index': 'no'},
                        },
                    },
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
                    'platforms': {'type': 'byte'},
                    'previews': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'long', 'index': 'no'},
                            'modified': {'type': 'date', 'index': 'no'},
                        },
                    },
                    'public_stats': {'type': 'boolean', 'index': 'no'},
                    'ratings': {
                        'type': 'object',
                        'properties': {
                            'count': {'type': 'short', 'index': 'no'},
                            'average': {'type': 'float', 'index': 'no'}
                        }
                    },
                    'slug': {'type': 'string'},
                    'status': {'type': 'byte'},
                    'summary': {'type': 'string', 'analyzer': 'snowball'},
                    'tags': {'type': 'string', 'index': 'not_analyzed'},
                    'type': {'type': 'byte'},
                    'view_source': {'type': 'boolean', 'index': 'no'},
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
    def extract_version(cls, obj, version_obj):
        return {
            'id': version_obj.pk,
            'compatible_apps': cls.extract_compatibility_info(version_obj),
            'files': [{
                'id': file_.id,
                'created': file_.created,
                'filename': file_.filename,
                'hash': file_.hash,
                'platform': file_.platform,
                'size': file_.size,
                'status': file_.status,
                'webext_permissions_list': file_.webext_permissions_list,
            } for file_ in version_obj.all_files],
            'reviewed': version_obj.reviewed,
            'version': version_obj.version,
        } if version_obj else None

    @classmethod
    def extract_compatibility_info(cls, version_obj):
        compatible_apps = {}
        for app, appver in version_obj.compatible_apps.items():
            if appver:
                min_, max_ = appver.min.version_int, appver.max.version_int
                min_human, max_human = appver.min.version, appver.max.version
            else:
                # Fake wide compatibility for search tools and personas.
                min_, max_ = 0, version_int('9999')
                min_human, max_human = None, None
            compatible_apps[app.id] = {
                'min': min_, 'min_human': min_human,
                'max': max_, 'max_human': max_human,
            }
        return compatible_apps

    @classmethod
    def extract_document(cls, obj):
        """Extract indexable attributes from an add-on."""
        from olympia.addons.models import Preview

        attrs = ('id', 'average_daily_users', 'bayesian_rating', 'created',
                 'default_locale', 'guid', 'hotness', 'icon_type',
                 'is_disabled', 'is_experimental', 'last_updated',
                 'modified', 'public_stats', 'slug', 'status', 'type',
                 'view_source', 'weekly_downloads')
        data = {attr: getattr(obj, attr) for attr in attrs}

        if obj.type == amo.ADDON_PERSONA:
            try:
                # Boost on popularity.
                data['boost'] = float(obj.persona.popularity ** .2)
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
            data['boost'] = float(obj.average_daily_users ** .2)
            data['has_theme_rereview'] = None

        data['app'] = [app.id for app in obj.compatible_apps.keys()]
        # Quadruple the boost if the add-on is public.
        if (obj.status == amo.STATUS_PUBLIC and not obj.is_experimental and
                'boost' in data):
            data['boost'] = float(max(data['boost'], 1) * 4)
        # We can use all_categories because the indexing code goes through the
        # transformer that sets it.
        data['category'] = [cat.id for cat in obj.all_categories]
        data['current_version'] = cls.extract_version(
            obj, obj.current_version)
        if obj.current_version:
            data['platforms'] = [p.id for p in
                                 obj.current_version.supported_platforms]
        data['current_beta_version'] = cls.extract_version(
            obj, obj.current_beta_version)
        data['listed_authors'] = [
            {'name': a.name, 'id': a.id, 'username': a.username}
            for a in obj.listed_authors
        ]

        data['has_eula'] = bool(obj.eula)
        data['has_privacy_policy'] = bool(obj.privacy_policy)

        data['latest_unlisted_version'] = cls.extract_version(
            obj, obj.latest_unlisted_version)

        # We can use all_previews because the indexing code goes through the
        # transformer that sets it.
        data['previews'] = [{'id': preview.id, 'modified': preview.modified}
                            for preview in obj.all_previews]
        data['ratings'] = {
            'average': obj.average_rating,
            'count': obj.total_reviews,
        }
        # We can use tag_list because the indexing code goes through the
        # transformer that sets it (attach_tags).
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
        # Also do that for preview captions, which are set on each preview
        # object.
        attach_trans_dict(Preview, obj.all_previews)
        for i, preview in enumerate(obj.all_previews):
            data['previews'][i].update(
                cls.extract_field_raw_translations(preview, 'caption'))

        # Finally, add the special sort field, coercing the current translation
        # into an unicode object first.
        data['name_sort'] = unicode(obj.name).lower()

        return data
