import copy

from django.conf import settings
from olympia.constants.promoted import RECOMMENDED

import olympia.core.logger
from olympia import amo
from olympia.amo.utils import attach_trans_dict
from olympia.amo.celery import create_chunked_tasks_signatures
from olympia.amo.utils import to_language
from olympia.constants.search import SEARCH_LANGUAGE_TO_ANALYZER
from olympia.lib.es.utils import create_index
from olympia.versions.compare import version_int


log = olympia.core.logger.getLogger('z.es')


class AddonIndexer:
    """
    Base Indexer class for add-ons.
    """

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
        for field_name in field_names:
            # _translations is the suffix in TranslationSerializer.
            mapping['properties'][
                '%s_translations' % field_name
            ] = cls.get_translations_definition()

    @classmethod
    def get_translations_definition(cls):
        """
        Return the mapping to use for raw translations (to be returned directly
        by the API, not used for analysis).
        See attach_translation_mappings() for more information.
        """
        return {
            'type': 'object',
            'properties': {
                'lang': {'type': 'text', 'index': False},
                'string': {'type': 'text', 'index': False},
            },
        }

    @classmethod
    def get_raw_field_definition(cls):
        """
        Return the mapping to use for the "raw" version of a field. Meant to be
        used as part of a 'fields': {'raw': ... } definition in the mapping of
        an existing field.

        Used for exact matches and sorting
        """
        # It needs to be a keyword to turnoff all analysis ; that means we
        # don't get the lowercase filter applied by the standard &
        # language-specific analyzers, so we need to do that ourselves through
        # a custom normalizer for exact matches to work in a case-insensitive
        # way.
        return {
            'type': 'keyword',
            'normalizer': 'lowercase_keyword_normalizer',
        }

    @classmethod
    def attach_language_specific_analyzers(cls, mapping, field_names):
        """
        For each field in field_names, attach language-specific mappings that
        will use specific analyzers for these fields in every language that we
        support.

        These mappings are used by the search filtering code if they exist.
        """
        for lang, analyzer in SEARCH_LANGUAGE_TO_ANALYZER.items():
            for field in field_names:
                property_name = '%s_l10n_%s' % (field, lang)
                mapping['properties'][property_name] = {
                    'type': 'text',
                    'analyzer': analyzer,
                }

    @classmethod
    def attach_language_specific_analyzers_with_raw_variant(cls, mapping, field_names):
        """
        Like attach_language_specific_analyzers() but with an extra field to
        storethe "raw" variant of the value, for exact matches.
        """
        for lang, analyzer in SEARCH_LANGUAGE_TO_ANALYZER.items():
            for field in field_names:
                property_name = '%s_l10n_%s' % (field, lang)
                mapping['properties'][property_name] = {
                    'type': 'text',
                    'analyzer': analyzer,
                    'fields': {
                        'raw': cls.get_raw_field_definition(),
                    },
                }

    @classmethod
    def extract_field_api_translations(cls, obj, field, db_field=None):
        """
        Returns a dict containing translations that we need to store for
        the API. Empty translations are skipped entirely.
        """
        if db_field is None:
            db_field = '%s_id' % field

        extend_with_me = {
            '%s_translations'
            % field: [
                {'lang': to_language(lang), 'string': str(string)}
                for lang, string in obj.translations[getattr(obj, db_field)]
                if string
            ]
        }
        return extend_with_me

    @classmethod
    def extract_field_search_translation(cls, obj, field, default_locale):
        """
        Returns the translation for this field in the object's default locale,
        in the form a dict with one entry (the field being the key and the
        translation being the value, or an empty string if none was found).

        That field will be analyzed and indexed by ES *without*
        language-specific analyzers.
        """
        translations = dict(obj.translations[getattr(obj, '%s_id' % field)])
        default_locale = default_locale.lower() if default_locale else None
        value = translations.get(default_locale, getattr(obj, field))

        return {field: str(value) if value else ''}

    @classmethod
    def extract_field_analyzed_translations(cls, obj, field, db_field=None):
        """
        Returns a dict containing translations for each language that we have
        an analyzer for, for the given field.

        When no translation exist for a given language+field combo, the value
        returned is an empty string, to avoid storing the word "None" as the
        field does not understand null values.
        """
        if db_field is None:
            db_field = '%s_id' % field

        translations = dict(obj.translations[getattr(obj, db_field)])

        return {
            '%s_l10n_%s' % (field, lang): translations.get(lang) or ''
            for lang in SEARCH_LANGUAGE_TO_ANALYZER
        }

    # Fields we don't need to expose in the results, only used for filtering
    # or sorting.
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

    index_settings = {
        'analysis': {
            'analyzer': {
                'standard_with_word_split': {
                    # This analyzer tries to split the text into words by using
                    # various methods. It also lowercases them and make sure
                    # each token is only returned once.
                    # Only use for short things with extremely meaningful
                    # content like add-on name - it makes too many
                    # modifications to be useful for things like descriptions,
                    # for instance.
                    'tokenizer': 'standard',
                    'filter': [
                        'custom_word_delimiter',
                        'lowercase',
                        'stop',
                        'custom_dictionary_decompounder',
                        'unique',
                    ],
                },
                'trigram': {
                    # Analyzer that splits the text into trigrams.
                    'tokenizer': 'ngram_tokenizer',
                    'filter': [
                        'lowercase',
                    ],
                },
            },
            'tokenizer': {
                'ngram_tokenizer': {
                    'type': 'ngram',
                    'min_gram': 3,
                    'max_gram': 3,
                    'token_chars': ['letter', 'digit'],
                }
            },
            'normalizer': {
                'lowercase_keyword_normalizer': {
                    # By default keywords are indexed 'as-is', but for exact
                    # name matches we need to lowercase them before indexing,
                    # so this normalizer does that for us.
                    'type': 'custom',
                    'filter': ['lowercase'],
                },
            },
            'filter': {
                'custom_word_delimiter': {
                    # This filter is useful for add-on names that have multiple
                    # words sticked together in a way that is easy to
                    # recognize, like FooBar, which should be indexed as FooBar
                    # and Foo Bar. (preserve_original: True makes us index both
                    # the original and the split version.)
                    'type': 'word_delimiter',
                    'preserve_original': True,
                },
                'custom_dictionary_decompounder': {
                    # This filter is also useful for add-on names that have
                    # multiple words sticked together, but without a pattern
                    # that we can automatically recognize. To deal with those,
                    # we use a small dictionary of common words. It allows us
                    # to index 'awesometabpassword'  as 'awesome tab password',
                    # helping users looking for 'tab password' find that addon.
                    'type': 'dictionary_decompounder',
                    'word_list': [
                        'all',
                        'auto',
                        'ball',
                        'bar',
                        'block',
                        'blog',
                        'bookmark',
                        'browser',
                        'bug',
                        'button',
                        'cat',
                        'chat',
                        'click',
                        'clip',
                        'close',
                        'color',
                        'context',
                        'cookie',
                        'cool',
                        'css',
                        'delete',
                        'dictionary',
                        'down',
                        'download',
                        'easy',
                        'edit',
                        'fill',
                        'fire',
                        'firefox',
                        'fix',
                        'flag',
                        'flash',
                        'fly',
                        'forecast',
                        'fox',
                        'foxy',
                        'google',
                        'grab',
                        'grease',
                        'html',
                        'http',
                        'image',
                        'input',
                        'inspect',
                        'inspector',
                        'iris',
                        'js',
                        'key',
                        'keys',
                        'lang',
                        'link',
                        'mail',
                        'manager',
                        'map',
                        'mega',
                        'menu',
                        'menus',
                        'monkey',
                        'name',
                        'net',
                        'new',
                        'open',
                        'password',
                        'persona',
                        'privacy',
                        'query',
                        'screen',
                        'scroll',
                        'search',
                        'secure',
                        'select',
                        'smart',
                        'spring',
                        'status',
                        'style',
                        'super',
                        'sync',
                        'tab',
                        'text',
                        'think',
                        'this',
                        'time',
                        'title',
                        'translate',
                        'tree',
                        'undo',
                        'upload',
                        'url',
                        'user',
                        'video',
                        'window',
                        'with',
                        'word',
                        'zilla',
                    ],
                },
            },
        }
    }

    @classmethod
    def get_model(cls):
        from olympia.addons.models import Addon

        return Addon

    @classmethod
    def get_index_alias(cls):
        """Return the index alias name."""
        return settings.ES_INDEXES.get('default')

    @classmethod
    def get_mapping(cls):
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
                'compatible_apps': {
                    'properties': {app.id: appver_mapping for app in amo.APP_USAGE}
                },
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
                        'filename': {'type': 'keyword', 'index': False},
                        'is_mozilla_signed_extension': {'type': 'boolean'},
                        'size': {'type': 'long', 'index': False},
                        'strict_compatibility': {'type': 'boolean', 'index': False},
                        'status': {'type': 'byte'},
                        'permissions': {'type': 'keyword', 'index': False},
                        'optional_permissions': {'type': 'keyword', 'index': False},
                    },
                },
                'license': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'long', 'index': False},
                        'builtin': {'type': 'short', 'index': False},
                        'name_translations': cls.get_translations_definition(),
                        'url': {'type': 'text', 'index': False},
                    },
                },
                'release_notes_translations': cls.get_translations_definition(),
                'version': {'type': 'keyword', 'index': False},
            },
        }
        mapping = {
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
                        },
                    },
                },
                'previews': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'long', 'index': False},
                        'caption_translations': cls.get_translations_definition(),
                        'modified': {'type': 'date', 'index': False},
                        'position': {'type': 'long', 'index': False},
                        'sizes': {
                            'type': 'object',
                            'properties': {
                                'thumbnail': {'type': 'short', 'index': False},
                                'image': {'type': 'short', 'index': False},
                            },
                        },
                    },
                },
                'promoted': {
                    'type': 'object',
                    'properties': {
                        'group_id': {'type': 'byte'},
                        'approved_for_apps': {'type': 'byte'},
                    },
                },
                'ratings': {
                    'type': 'object',
                    'properties': {
                        'count': {'type': 'short', 'index': False},
                        'average': {'type': 'float'},
                    },
                },
                'slug': {'type': 'keyword'},
                'requires_payment': {'type': 'boolean', 'index': False},
                'status': {'type': 'byte'},
                'summary': {'type': 'text', 'analyzer': 'snowball'},
                'tags': {'type': 'keyword'},
                'type': {'type': 'byte'},
                'weekly_downloads': {'type': 'long'},
            },
        }

        # Add fields that we expect to return all translations without being
        # analyzed/indexed.
        cls.attach_translation_mappings(
            mapping,
            (
                'description',
                'developer_comments',
                'homepage',
                'name',
                'summary',
                'support_email',
                'support_url',
            ),
        )

        # Add language-specific analyzers for localized fields that are
        # analyzed/indexed.
        cls.attach_language_specific_analyzers(mapping, ('description', 'summary'))

        cls.attach_language_specific_analyzers_with_raw_variant(mapping, ('name',))

        return mapping

    @classmethod
    def extract_version(cls, obj, version_obj):
        from olympia.versions.models import License, Version

        data = (
            {
                'id': version_obj.pk,
                'compatible_apps': cls.extract_compatibility_info(obj, version_obj),
                'files': [
                    {
                        'id': version_obj.file.id,
                        'created': version_obj.file.created,
                        'filename': version_obj.file.file.name,
                        'hash': version_obj.file.hash,
                        'is_mozilla_signed_extension': (
                            version_obj.file.is_mozilla_signed_extension
                        ),
                        'size': version_obj.file.size,
                        'status': version_obj.file.status,
                        'strict_compatibility': version_obj.file.strict_compatibility,
                        'permissions': version_obj.file.permissions,
                        'optional_permissions': version_obj.file.optional_permissions,
                    }
                ],
                'reviewed': version_obj.reviewed,
                'version': version_obj.version,
            }
            if version_obj
            else None
        )
        if data and version_obj:
            attach_trans_dict(Version, [version_obj])
            data.update(
                cls.extract_field_api_translations(
                    version_obj, 'release_notes', db_field='release_notes_id'
                )
            )
            if version_obj.license:
                data['license'] = {
                    'id': version_obj.license.id,
                    'builtin': version_obj.license.builtin,
                    'url': version_obj.license.url,
                }
                attach_trans_dict(License, [version_obj.license])
                data['license'].update(
                    cls.extract_field_api_translations(version_obj.license, 'name')
                )
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
                if not version_obj.file.strict_compatibility:
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
                min_human, max_human = (
                    amo.DEFAULT_WEBEXT_MIN_VERSIONS.get(
                        app, amo.DEFAULT_WEBEXT_MIN_VERSION
                    ),
                    amo.FAKE_MAX_VERSION,
                )
                min_, max_ = version_int(min_human), version_int(max_human)
            compatible_apps[app.id] = {
                'min': min_,
                'min_human': min_human,
                'max': max_,
                'max_human': max_human,
            }
        return compatible_apps

    @classmethod
    def extract_document(cls, obj):
        """Extract indexable attributes from an add-on."""
        from olympia.addons.models import Preview

        attrs = (
            'id',
            'average_daily_users',
            'bayesian_rating',
            'contributions',
            'created',
            'default_locale',
            'guid',
            'hotness',
            'icon_hash',
            'icon_type',
            'is_disabled',
            'is_experimental',
            'last_updated',
            'modified',
            'requires_payment',
            'slug',
            'status',
            'type',
            'weekly_downloads',
        )
        data = {attr: getattr(obj, attr) for attr in attrs}

        data['colors'] = None
        # Extract dominant colors from static themes.
        if obj.type == amo.ADDON_STATICTHEME:
            if obj.current_previews:
                data['colors'] = obj.current_previews[0].colors

        data['app'] = [app.id for app in obj.compatible_apps.keys()]
        # Boost by the number of users on a logarithmic scale.
        data['boost'] = float(data['average_daily_users'] ** 0.2)
        # Quadruple the boost if the add-on is public.
        if (
            obj.status == amo.STATUS_APPROVED
            and not obj.is_experimental
            and 'boost' in data
        ):
            data['boost'] = float(max(data['boost'], 1) * 4)
        # We can use all_categories because the indexing code goes through the
        # transformer that sets it.
        data['category'] = [cat.id for cat in obj.all_categories]
        data['current_version'] = cls.extract_version(obj, obj.current_version)
        data['listed_authors'] = [
            {
                'name': a.name,
                'id': a.id,
                'username': a.username,
                'is_public': a.is_public,
            }
            for a in obj.listed_authors
        ]

        data['has_eula'] = bool(obj.eula)
        data['has_privacy_policy'] = bool(obj.privacy_policy)

        data['is_recommended'] = bool(
            obj.promoted and obj.promoted.group == RECOMMENDED
        )

        data['previews'] = [
            {
                'id': preview.id,
                'modified': preview.modified,
                'sizes': preview.sizes,
                'position': preview.position,
            }
            for preview in obj.current_previews
        ]

        data['promoted'] = (
            {
                'group_id': obj.promoted.group_id,
                # store the app approvals because .approved_applications needs it.
                'approved_for_apps': [
                    app.id for app in obj.promoted.approved_applications
                ],
            }
            if obj.promoted
            else None
        )

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
            data.update(
                cls.extract_field_search_translation(obj, field, obj.default_locale)
            )
            data.update(cls.extract_field_analyzed_translations(obj, field))

        # Then add fields that only need to be returned to the API without
        # contributing to search relevancy.
        for field in ('developer_comments', 'homepage', 'support_email', 'support_url'):
            data.update(cls.extract_field_api_translations(obj, field))
        if obj.type != amo.ADDON_STATICTHEME:
            # Also do that for preview captions, which are set on each preview
            # object.
            attach_trans_dict(Preview, obj.current_previews)
            for i, preview in enumerate(obj.current_previews):
                data['previews'][i].update(
                    cls.extract_field_api_translations(preview, 'caption')
                )

        return data

    @classmethod
    def create_new_index(cls, index_name):
        """
        Create a new index for addons in ES.

        Intended to be used by reindexation (and tests), generally a bad idea
        to call manually.
        """
        index_settings = copy.deepcopy(cls.index_settings)

        config = {
            'mappings': cls.get_mapping(),
            'settings': {
                # create_index will add its own index settings like number of
                # shards and replicas.
                'index': index_settings
            },
        }
        create_index(index_name, config)

    @classmethod
    def reindex_tasks_group(cls, index_name):
        """
        Return the group of tasks to execute for a full reindex of addons on
        the index called `index_name` (which is not an alias but the real
        index name).
        """
        from olympia.addons.tasks import index_addons

        ids = cls.get_model().unfiltered.values_list('id', flat=True).order_by('id')
        chunk_size = 150
        return create_chunked_tasks_signatures(
            index_addons, list(ids), chunk_size, task_kwargs={'index': index_name}
        )
