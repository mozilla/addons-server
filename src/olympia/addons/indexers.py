from django.core.exceptions import ObjectDoesNotExist

import olympia.core.logger
from olympia import amo
from olympia.amo.indexers import BaseSearchIndexer
from olympia.amo.utils import attach_trans_dict
from olympia.versions.compare import version_int


log = olympia.core.logger.getLogger('z.es')


# When the 'boost-webextensions-in-search' waffle switch is enabled, queries
# against the addon index should be scored to assign this weight to
# webextensions.
# The value is used to multiply matching documents score.A value of 1 is
# neutral.
WEBEXTENSIONS_WEIGHT = 2.0


class AddonIndexer(BaseSearchIndexer):
    """Fields we don't need to expose in the results, only used for filtering
    or sorting."""
    hidden_fields = (
        'name_sort',
        'boost',
        'hotness',
        # Translated content that is used for filtering purposes is stored
        # under 3 different fields:
        # - One field with all translations (e.g., "name").
        # - One field for each language, with language-specific analyzers
        #   (e.g., "name_l10n_italian", "name_l10n_french", etc.)
        # - One field with all translations in separate objects for the API
        #   (e.g. "name_translations")
        # Only that last one with all translations needs to be returned.
        'name',
        'description',
        'name_l10n_*',
        'description_l10n_*',
        'summary',
        'summary_l10n_*',
    )

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
                'max_human': {'type': 'keyword', 'index': False},
                'min_human': {'type': 'keyword', 'index': False},
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
                'reviewed': {'type': 'date', 'index': False},
                'files': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'long', 'index': False},
                        'created': {'type': 'date', 'index': False},
                        'hash': {'type': 'keyword', 'index': False},
                        'filename': {
                            'type': 'keyword', 'index': False},
                        'is_webextension': {'type': 'boolean'},
                        'is_restart_required': {
                            'type': 'boolean', 'index': False},
                        'platform': {
                            'type': 'byte', 'index': False},
                        'size': {'type': 'long', 'index': False},
                        'strict_compatibility': {
                            'type': 'boolean', 'index': False},
                        'status': {'type': 'byte'},
                        'webext_permissions_list': {
                            'type': 'keyword', 'index': False},
                    }
                },
                'version': {'type': 'keyword', 'index': False},
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
                    'default_locale': {'type': 'keyword', 'index': False},
                    'description': {'type': 'text', 'analyzer': 'snowball'},
                    'guid': {'type': 'keyword', 'index': False},
                    'has_eula': {'type': 'boolean', 'index': False},
                    'has_privacy_policy': {'type': 'boolean', 'index': False},
                    'has_theme_rereview': {'type': 'boolean'},
                    'hotness': {'type': 'double'},
                    'icon_type': {'type': 'keyword', 'index': False},
                    'is_disabled': {'type': 'boolean'},
                    'is_experimental': {'type': 'boolean'},
                    'is_featured': {'type': 'boolean'},
                    'last_updated': {'type': 'date'},
                    'latest_unlisted_version': version_mapping,
                    'listed_authors': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'long', 'index': False},
                            'name': {'type': 'text'},
                            'username': {'type': 'keyword'},
                        },
                    },
                    'modified': {'type': 'date', 'index': False},
                    # Adding word-delimiter to split on camelcase and
                    # punctuation.
                    'name': {'type': 'text',
                             'analyzer': 'standardPlusWordDelimiter'},
                    # Turn off analysis on name so we can sort by it.
                    'name_sort': {'type': 'keyword'},
                    'persona': {
                        'type': 'object',
                        'properties': {
                            'accentcolor': {'type': 'keyword', 'index': False},
                            'author': {'type': 'keyword', 'index': False},
                            'header': {'type': 'keyword', 'index': False},
                            'footer': {'type': 'keyword', 'index': False},
                            'is_new': {'type': 'boolean', 'index': False},
                            'textcolor': {'type': 'keyword', 'index': False},
                        }
                    },
                    'platforms': {'type': 'byte'},
                    'previews': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'long', 'index': False},
                            'modified': {'type': 'date', 'index': False},
                        },
                    },
                    'public_stats': {'type': 'boolean', 'index': False},
                    'ratings': {
                        'type': 'object',
                        'properties': {
                            'count': {'type': 'short', 'index': False},
                            'average': {'type': 'float', 'index': False}
                        }
                    },
                    'slug': {'type': 'text'},
                    'requires_payment': {'type': 'boolean', 'index': False},
                    'status': {'type': 'byte'},
                    'summary': {'type': 'text', 'analyzer': 'snowball'},
                    'tags': {'type': 'keyword'},
                    'type': {'type': 'byte'},
                    'view_source': {'type': 'boolean', 'index': False},
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
                'is_webextension': file_.is_webextension,
                'is_restart_required': file_.is_restart_required,
                'platform': file_.platform,
                'size': file_.size,
                'status': file_.status,
                'strict_compatibility': file_.strict_compatibility,
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
                if not version_obj.files.filter(
                        strict_compatibility=True).exists():
                    # The files attached to this version are not using strict
                    # compatibility, so the max version essentially needs to be
                    # ignored - let's fake a super high one. We leave max_human
                    # alone to leave the API representation intact.
                    max_ = version_int('9999')
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
                 'modified', 'public_stats', 'requires_payment', 'slug',
                 'status', 'type', 'view_source', 'weekly_downloads')
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

        data['is_featured'] = obj.is_featured(None, None)

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
