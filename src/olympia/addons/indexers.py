import copy

import waffle

import olympia.core.logger
from olympia import amo
from olympia.amo.indexers import BaseSearchIndexer
from olympia.amo.utils import attach_trans_dict
from olympia.amo.celery import create_chunked_tasks_signatures
from olympia.lib.es.utils import create_index
from olympia.versions.compare import version_int


log = olympia.core.logger.getLogger('z.es')


class AddonIndexer(BaseSearchIndexer):
    """Fields we don't need to expose in the results, only used for filtering
    or sorting."""
    hidden_fields = (
        '*.raw',
        'boost',
        'colors',
        'hotness',
        # Translated content that is used for filtering purposes is stored
        # under 3 different fields:
        # - One field with all translations (e.g., "name").
        # - One field for each language, using corresponding analyzer
        #   (e.g., "name_l10n_en-us", "name_l10n_fr", etc.)
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
                        'is_mozilla_signed_extension': {'type': 'boolean'},
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
                'license': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'long', 'index': False},
                        'builtin': {'type': 'boolean', 'index': False},
                        'name_translations': cls.get_translations_definition(),
                        'url': {'type': 'text', 'index': False}
                    },
                },
                'release_notes_translations':
                    cls.get_translations_definition(),
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
                    'boost': {'type': 'float', 'null_value': 1.0},
                    'category': {'type': 'integer'},
                    'colors': {
                        'type': 'nested',
                        'properties': {
                            'h': {'type': 'integer'},
                            's': {'type': 'integer'},
                            'l': {'type': 'integer'},
                            'ratio': {'type': 'double'},
                        },
                    },
                    'contributions': {'type': 'text'},
                    'created': {'type': 'date'},
                    'current_version': version_mapping,
                    'default_locale': {'type': 'keyword', 'index': False},
                    'description': {'type': 'text', 'analyzer': 'snowball'},
                    'guid': {'type': 'keyword'},
                    'has_eula': {'type': 'boolean', 'index': False},
                    'has_privacy_policy': {'type': 'boolean', 'index': False},
                    'hotness': {'type': 'double'},
                    'icon_hash': {'type': 'keyword', 'index': False},
                    'icon_type': {'type': 'keyword', 'index': False},
                    'is_disabled': {'type': 'boolean'},
                    'is_experimental': {'type': 'boolean'},
                    'is_recommended': {'type': 'boolean'},
                    'last_updated': {'type': 'date'},
                    'listed_authors': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'long'},
                            'name': {'type': 'text'},
                            'username': {'type': 'keyword'},
                            'is_public': {'type': 'boolean', 'index': False},
                        },
                    },
                    'modified': {'type': 'date', 'index': False},
                    'name': {
                        'type': 'text',
                        # Adding word-delimiter to split on camelcase, known
                        # words like 'tab', and punctuation, and eliminate
                        # duplicates.
                        'analyzer': 'standard_with_word_split',
                        'fields': {
                            # Raw field for exact matches and sorting.
                            'raw': cls.get_raw_field_definition(),
                            # Trigrams for partial matches.
                            'trigrams': {
                                'type': 'text',
                                'analyzer': 'trigram',
                            }
                        }
                    },
                    'platforms': {'type': 'byte'},
                    'previews': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'long', 'index': False},
                            'caption_translations':
                                cls.get_translations_definition(),
                            'modified': {'type': 'date', 'index': False},
                            'sizes': {
                                'type': 'object',
                                'properties': {
                                    'thumbnail': {'type': 'short',
                                                  'index': False},
                                    'image': {'type': 'short', 'index': False},
                                },
                            },
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
                    'slug': {'type': 'keyword'},
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
            mapping, ('description', 'developer_comments', 'homepage', 'name',
                      'summary', 'support_email', 'support_url'))

        # Add language-specific analyzers for localized fields that are
        # analyzed/indexed.
        cls.attach_language_specific_analyzers(
            mapping, ('description', 'summary'))

        cls.attach_language_specific_analyzers_with_raw_variant(
            mapping, ('name',))

        return mapping

    @classmethod
    def extract_version(cls, obj, version_obj):
        from olympia.versions.models import License, Version

        data = {
            'id': version_obj.pk,
            'compatible_apps': cls.extract_compatibility_info(
                obj, version_obj),
            'files': [{
                'id': file_.id,
                'created': file_.created,
                'filename': file_.filename,
                'hash': file_.hash,
                'is_webextension': file_.is_webextension,
                'is_mozilla_signed_extension': (
                    file_.is_mozilla_signed_extension),
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
        if data and version_obj:
            attach_trans_dict(Version, [version_obj])
            data.update(cls.extract_field_api_translations(
                version_obj, 'release_notes', db_field='release_notes_id'))
            if version_obj.license:
                data['license'] = {
                    'id': version_obj.license.id,
                    'builtin': version_obj.license.builtin,
                    'url': version_obj.license.url,
                }
                attach_trans_dict(License, [version_obj.license])
                data['license'].update(cls.extract_field_api_translations(
                    version_obj.license, 'name'))
        return data

    @classmethod
    def extract_compatibility_info(cls, obj, version_obj):
        """Return compatibility info for the specified version_obj, as will be
        indexed in ES."""
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
                    max_ = version_int('*')
            else:
                # Fake wide compatibility for add-ons with no info. We don't
                # want to reindex every time a new version of the app is
                # released, so we directly index a super high version as the
                # max.
                min_human, max_human = amo.D2C_MIN_VERSIONS.get(
                    app.id, '1.0'), amo.FAKE_MAX_VERSION,
                min_, max_ = version_int(min_human), version_int(max_human)
            compatible_apps[app.id] = {
                'min': min_, 'min_human': min_human,
                'max': max_, 'max_human': max_human,
            }
        return compatible_apps

    @classmethod
    def extract_document(cls, obj):
        """Extract indexable attributes from an add-on."""
        from olympia.addons.models import Preview

        attrs = ('id', 'average_daily_users', 'bayesian_rating',
                 'contributions', 'created',
                 'default_locale', 'guid', 'hotness', 'icon_hash', 'icon_type',
                 'is_disabled', 'is_experimental', 'is_recommended',
                 'last_updated',
                 'modified', 'public_stats', 'requires_payment', 'slug',
                 'status', 'type', 'view_source', 'weekly_downloads')
        data = {attr: getattr(obj, attr) for attr in attrs}

        data['colors'] = None
        if obj.current_version:
            data['platforms'] = [p.id for p in
                                 obj.current_version.supported_platforms]

        # Extract dominant colors from static themes.
        if obj.type == amo.ADDON_STATICTHEME:
            first_preview = obj.current_previews.first()
            if first_preview:
                data['colors'] = first_preview.colors

        data['app'] = [app.id for app in obj.compatible_apps.keys()]
        # Boost by the number of users on a logarithmic scale.
        data['boost'] = float(data['average_daily_users'] ** .2)
        # Quadruple the boost if the add-on is public.
        if (obj.status == amo.STATUS_APPROVED and not obj.is_experimental and
                'boost' in data):
            data['boost'] = float(max(data['boost'], 1) * 4)
        # We can use all_categories because the indexing code goes through the
        # transformer that sets it.
        data['category'] = [cat.id for cat in obj.all_categories]
        data['current_version'] = cls.extract_version(
            obj, obj.current_version)
        data['listed_authors'] = [
            {'name': a.name, 'id': a.id, 'username': a.username,
             'is_public': a.is_public}
            for a in obj.listed_authors
        ]

        data['has_eula'] = bool(obj.eula)
        data['has_privacy_policy'] = bool(obj.privacy_policy)

        data['previews'] = [{'id': preview.id, 'modified': preview.modified,
                             'sizes': preview.sizes}
                            for preview in obj.current_previews]
        data['ratings'] = {
            'average': obj.average_rating,
            'count': obj.total_ratings,
            'text_count': obj.text_ratings_count,
        }
        # We can use tag_list because the indexing code goes through the
        # transformer that sets it (attach_tags).
        data['tags'] = getattr(obj, 'tag_list', [])

        # Handle localized fields.
        # First, deal with the 3 fields that need everything:
        for field in ('description', 'name', 'summary'):
            data.update(cls.extract_field_api_translations(obj, field))
            data.update(cls.extract_field_search_translation(
                obj, field, obj.default_locale))
            data.update(cls.extract_field_analyzed_translations(obj, field))

        # Then add fields that only need to be returned to the API without
        # contributing to search relevancy.
        for field in ('developer_comments', 'homepage', 'support_email',
                      'support_url'):
            data.update(cls.extract_field_api_translations(obj, field))
        if obj.type != amo.ADDON_STATICTHEME:
            # Also do that for preview captions, which are set on each preview
            # object.
            attach_trans_dict(Preview, obj.current_previews)
            for i, preview in enumerate(obj.current_previews):
                data['previews'][i].update(
                    cls.extract_field_api_translations(preview, 'caption'))

        return data


# addons index settings.
INDEX_SETTINGS = {
    'analysis': {
        'analyzer': {
            'standard_with_word_split': {
                # This analyzer tries to split the text into words by using
                # various methods. It also lowercases them and make sure each
                # token is only returned once.
                # Only use for short things with extremely meaningful content
                # like add-on name - it makes too many modifications to be
                # useful for things like descriptions, for instance.
                'tokenizer': 'standard',
                'filter': [
                    'standard', 'custom_word_delimiter', 'lowercase', 'stop',
                    'custom_dictionary_decompounder', 'unique',
                ]
            },
            'trigram': {
                # Analyzer that splits the text into trigrams.
                'tokenizer': 'ngram_tokenizer',
                'filter': [
                    'lowercase',
                ]
            },
        },
        'tokenizer': {
            'ngram_tokenizer': {
                'type': 'ngram',
                'min_gram': 3,
                'max_gram': 3,
                'token_chars': ['letter', 'digit']
            }
        },
        'normalizer': {
            'lowercase_keyword_normalizer': {
                # By default keywords are indexed 'as-is', but for exact name
                # matches we need to lowercase them before indexing, so this
                # normalizer does that for us.
                'type': 'custom',
                'filter': ['lowercase'],
            },
        },
        'filter': {
            'custom_word_delimiter': {
                # This filter is useful for add-on names that have multiple
                # words sticked together in a way that is easy to recognize,
                # like FooBar, which should be indexed as FooBar and Foo Bar.
                # (preserve_original: True makes us index both the original
                # and the split version.)
                'type': 'word_delimiter',
                'preserve_original': True
            },
            'custom_dictionary_decompounder': {
                # This filter is also useful for add-on names that have
                # multiple words sticked together, but without a pattern that
                # we can automatically recognize. To deal with those, we use
                # a small dictionary of common words. It allows us to index
                # 'awesometabpassword'  as 'awesome tab password', helping
                # users looking for 'tab password' find that add-on.
                'type': 'dictionary_decompounder',
                'word_list': [
                    'all', 'auto', 'ball', 'bar', 'block', 'blog', 'bookmark',
                    'browser', 'bug', 'button', 'cat', 'chat', 'click', 'clip',
                    'close', 'color', 'context', 'cookie', 'cool', 'css',
                    'delete', 'dictionary', 'down', 'download', 'easy', 'edit',
                    'fill', 'fire', 'firefox', 'fix', 'flag', 'flash', 'fly',
                    'forecast', 'fox', 'foxy', 'google', 'grab', 'grease',
                    'html', 'http', 'image', 'input', 'inspect', 'inspector',
                    'iris', 'js', 'key', 'keys', 'lang', 'link', 'mail',
                    'manager', 'map', 'mega', 'menu', 'menus', 'monkey',
                    'name', 'net', 'new', 'open', 'password', 'persona',
                    'privacy', 'query', 'screen', 'scroll', 'search', 'secure',
                    'select', 'smart', 'spring', 'status', 'style', 'super',
                    'sync', 'tab', 'text', 'think', 'this', 'time', 'title',
                    'translate', 'tree', 'undo', 'upload', 'url', 'user',
                    'video', 'window', 'with', 'word', 'zilla',
                ]
            },
        }
    }
}


def create_new_index(index_name=None):
    """
    Create a new index for addons in ES.

    Intended to be used by reindexation (and tests), generally a bad idea to
    call manually.
    """
    if index_name is None:
        index_name = AddonIndexer.get_index_alias()

    index_settings = copy.deepcopy(INDEX_SETTINGS)

    if waffle.switch_is_active('es-use-classic-similarity'):
        # http://bit.ly/es5-similarity-module-docs
        index_settings['similarity'] = {
            'default': {
                'type': 'classic'
            }
        }

    config = {
        'mappings': get_mappings(),
        'settings': {
            # create_index will add its own index settings like number of
            # shards and replicas.
            'index': index_settings
        },
    }
    create_index(index_name, config)


def get_mappings():
    """
    Return a dict with all addons-related ES mappings.
    """
    indexers = (AddonIndexer,)
    return {idxr.get_doctype_name(): idxr.get_mapping() for idxr in indexers}


def reindex_tasks_group(index_name):
    """
    Return the group of tasks to execute for a full reindex of addons on the
    index called `index_name` (which is not an alias but the real index name).
    """
    from olympia.addons.models import Addon
    from olympia.addons.tasks import index_addons

    ids = Addon.unfiltered.values_list('id', flat=True).order_by('id')
    chunk_size = 150
    return create_chunked_tasks_signatures(index_addons, list(ids), chunk_size)
