from itertools import chain
from unittest import mock

from django.conf import settings

from olympia import amo
from olympia.addons.indexers import AddonIndexer
from olympia.addons.models import Addon, Preview, attach_tags, attach_translations_dict
from olympia.amo.tests import (
    ESTestCase,
    TestCase,
    addon_factory,
)
from olympia.bandwagon.models import Collection
from olympia.constants.applications import FIREFOX
from olympia.constants.licenses import LICENSES_BY_BUILTIN
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.constants.search import SEARCH_LANGUAGE_TO_ANALYZER
from olympia.files.models import WebextPermission
from olympia.promoted.models import PromotedApproval
from olympia.versions.compare import version_int
from olympia.versions.models import License, VersionPreview


class TestAddonIndexer(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    # The base list of fields we expect to see in the mapping/extraction.
    # This only contains the fields for which we use the value directly,
    # see expected_fields() for the rest.
    simple_fields = [
        'average_daily_users',
        'bayesian_rating',
        'contributions',
        'created',
        'default_locale',
        'guid',
        'hotness',
        'icon_hash',
        'icon_type',
        'id',
        'is_disabled',
        'is_experimental',
        'last_updated',
        'modified',
        'requires_payment',
        'slug',
        'status',
        'type',
        'weekly_downloads',
    ]

    def setUp(self):
        super().setUp()
        self.transforms = (attach_tags, attach_translations_dict)
        self.indexer = AddonIndexer()
        self.addon = Addon.objects.get(pk=3615)

    @classmethod
    def expected_fields(cls, include_nullable=True):
        """
        Returns a list of fields we expect to be present in the mapping and
        in the extraction method.

        Should be updated whenever you change the mapping to add/remove fields.
        """
        # Fields that can not be directly compared with the property of the
        # same name on the Addon instance, either because the property doesn't
        # exist on the model, or it has a different name, or the value we need
        # to store in ES differs from the one in the db.
        complex_fields = [
            'app',
            'boost',
            'category',
            'colors',
            'current_version',
            'description',
            'has_eula',
            'has_privacy_policy',
            'is_recommended',
            'listed_authors',
            'name',
            'previews',
            'promoted',
            'ratings',
            'summary',
            'tags',
        ]

        # Fields that need to be present in the mapping, but might be skipped
        # for extraction because they can be null.
        nullable_fields = []

        # For each translated field that needs to be indexed, we store one
        # version for each language we have an analyzer for.
        _indexed_translated_fields = ('name', 'description', 'summary')
        analyzer_fields = list(
            chain.from_iterable(
                [
                    [
                        f'{field}_l10n_{lang}'
                        for lang, analyzer in SEARCH_LANGUAGE_TO_ANALYZER.items()
                    ]
                    for field in _indexed_translated_fields
                ]
            )
        )

        # It'd be annoying to hardcode `analyzer_fields`, so we generate it,
        # but to make sure the test is correct we still do a simple check of
        # the length to make sure we properly flattened the list.
        assert len(analyzer_fields) == (
            len(SEARCH_LANGUAGE_TO_ANALYZER) * len(_indexed_translated_fields)
        )

        # Each translated field that we want to return to the API.
        raw_translated_fields = [
            '%s_translations' % field
            for field in [
                'name',
                'description',
                'developer_comments',
                'homepage',
                'summary',
                'support_email',
                'support_url',
            ]
        ]

        # Return a list with the base fields and the dynamic ones added.
        fields = (
            cls.simple_fields + complex_fields + analyzer_fields + raw_translated_fields
        )
        if include_nullable:
            fields += nullable_fields
        return fields

    def test_mapping(self):
        mapping_properties = self.indexer.get_mapping()['properties']

        # Make sure the get_mapping() method does not return fields we did
        # not expect to be present, or omitted fields we want.
        assert set(mapping_properties.keys()) == set(self.expected_fields())

        # Make sure default_locale and translated fields are not indexed.
        assert mapping_properties['default_locale']['index'] is False
        name_translations = mapping_properties['name_translations']
        assert name_translations['properties']['lang']['index'] is False
        assert name_translations['properties']['string']['index'] is False

        # Make sure current_version mapping is set.
        assert mapping_properties['current_version']['properties']
        version_mapping = mapping_properties['current_version']['properties']
        expected_version_keys = (
            'id',
            'compatible_apps',
            'files',
            'license',
            'release_notes_translations',
            'reviewed',
            'version',
        )
        assert set(version_mapping.keys()) == set(expected_version_keys)

        # Make sure files mapping is set inside current_version.
        files_mapping = version_mapping['files']['properties']
        expected_file_keys = (
            'id',
            'created',
            'filename',
            'hash',
            'is_mozilla_signed_extension',
            'size',
            'status',
            'strict_compatibility',
            'permissions',
            'optional_permissions',
            'host_permissions',
            'data_collection_permissions',
            'optional_data_collection_permissions',
        )
        assert set(files_mapping.keys()) == set(expected_file_keys)

    def test_index_setting_boolean(self):
        """Make sure that the `index` setting is a true/false boolean.

        Old versions of ElasticSearch allowed 'no' and 'yes' strings,
        this changed with ElasticSearch 5.x.
        """
        mapping_properties = self.indexer.get_mapping()['properties']

        assert all(
            isinstance(prop['index'], bool)
            for prop in mapping_properties.values()
            if 'index' in prop
        )

        # Make sure our version_mapping is setup correctly too.
        props = mapping_properties['current_version']['properties']

        assert all(
            isinstance(prop['index'], bool)
            for prop in props.values()
            if 'index' in prop
        )

        # As well as for current_version.files
        assert all(
            isinstance(prop['index'], bool)
            for prop in props['files']['properties'].values()
            if 'index' in prop
        )

    def _extract(self):
        qs = Addon.unfiltered.filter(id__in=[self.addon.pk])
        for t in self.transforms:
            qs = qs.transform(t)
        self.addon = list(qs)[0]
        return self.indexer.extract_document(self.addon)

    def test_extract_attributes(self):
        extracted = self._extract()

        # Like test_mapping() above, but for the extraction process:
        # Make sure the method does not return fields we did not expect to be
        # present, or omitted fields we want.
        assert set(extracted.keys()) == set(
            self.expected_fields(include_nullable=False)
        )

        # Check base fields values. Other tests below check the dynamic ones.
        for field_name in self.simple_fields:
            assert extracted[field_name] == getattr(self.addon, field_name)

        assert extracted['app'] == [FIREFOX.id]
        assert extracted['boost'] == self.addon.average_daily_users**0.2 * 4
        assert extracted['category'] == [1, 22, 71]  # From fixture.
        assert extracted['current_version']
        assert extracted['listed_authors'] == [
            {'name': '55021 التطب', 'id': 55021, 'username': '55021'}
        ]
        assert extracted['ratings'] == {
            'average': self.addon.average_rating,
            'count': self.addon.total_ratings,
            'text_count': self.addon.text_ratings_count,
        }
        assert extracted['tags'] == []
        assert extracted['has_eula'] is True
        assert extracted['has_privacy_policy'] is True
        assert extracted['colors'] is None

    def test_extract_eula_privacy_policy(self):
        # Remove eula.
        self.addon.eula_id = None
        # Empty privacy policy should not be considered.
        self.addon.privacy_policy_id = ''
        self.addon.save()
        extracted = self._extract()

        assert extracted['has_eula'] is False
        assert extracted['has_privacy_policy'] is False

    def test_extract_no_current_version(self):
        self.addon.current_version.delete()
        extracted = self._extract()

        assert extracted['current_version'] is None

    def test_extract_version_and_files(self):
        permissions = ['bookmarks', 'random permission']
        optional_permissions = ['cookies', 'optional permission']
        host_permissions = ['https://example.com', 'https://mozilla.com']
        data_collection_permissions = ['none']
        optional_data_collection_permissions = [
            'technicalAndInteraction',
        ]
        version = self.addon.current_version
        # Add a bunch of things to it to test different scenarios.
        version.license = License.objects.create(name='My licensé', builtin=3)
        [
            WebextPermission.objects.create(
                file=version.file,
                permissions=permissions,
                optional_permissions=optional_permissions,
                host_permissions=host_permissions,
                data_collection_permissions=data_collection_permissions,
                optional_data_collection_permissions=(
                    optional_data_collection_permissions
                ),
            )
        ]
        version.save()

        # Now we can run the extraction and start testing.
        extracted = self._extract()

        assert extracted['current_version']
        assert extracted['current_version']['id'] == version.pk
        # Because strict_compatibility is False, the max version we record in
        # the index is an arbitrary super high version.
        assert extracted['current_version']['compatible_apps'] == {
            FIREFOX.id: {
                'min': 2000000200100,
                'max': version_int('*'),
                'max_human': '4.0',
                'min_human': '2.0',
            }
        }
        assert extracted['current_version']['license'] == {
            'builtin': 3,
            'id': version.license.pk,
            'name_translations': [{'lang': 'en-US', 'string': 'My licensé'}],
            'url': LICENSES_BY_BUILTIN[3].url,
        }
        assert extracted['current_version']['release_notes_translations'] == [
            {'lang': 'en-US', 'string': 'Fix for an important bug'},
            {
                'lang': 'fr',
                'string': "Quelque chose en fran\xe7ais.\n\nQuelque chose d'autre.",
            },
        ]
        assert extracted['current_version']['reviewed'] == version.human_review_date
        assert extracted['current_version']['version'] == version.version
        extracted_file = extracted['current_version']['files'][0]
        assert extracted_file['id'] == version.file.pk
        assert extracted_file['created'] == version.file.created
        assert extracted_file['filename'] == version.file.file.name
        assert extracted_file['hash'] == version.file.hash
        assert extracted_file['is_mozilla_signed_extension'] == (
            version.file.is_mozilla_signed_extension
        )
        assert extracted_file['size'] == version.file.size
        assert extracted_file['status'] == version.file.status
        assert extracted_file['permissions'] == permissions
        assert extracted_file['optional_permissions'] == optional_permissions
        assert extracted_file['host_permissions'] == host_permissions
        assert (
            extracted_file['data_collection_permissions'] == data_collection_permissions
        )
        assert (
            extracted_file['optional_data_collection_permissions']
            == optional_data_collection_permissions
        )

    def test_version_compatibility_with_strict_compatibility_enabled(self):
        version = self.addon.current_version
        version.file.update(strict_compatibility=True)
        extracted = self._extract()

        assert extracted['current_version']['compatible_apps'] == {
            FIREFOX.id: {
                'min': 2000000200100,
                'max': 4000000200100,
                'max_human': '4.0',
                'min_human': '2.0',
            }
        }

    def test_extract_translations(self):
        translations_name = {
            'en-US': 'Name in ënglish',
            'es-ES': 'Name in Español',
            'it': None,  # Empty name should be ignored in extract.
        }
        translations_description = {
            'en-US': 'Description in ënglish',
            'es-ES': 'Description in Español',
            'fr': '',  # Empty description should be ignored in extract.
            'it': '<script>alert(42)</script>',
        }
        self.addon.summary_id = None
        self.addon.name = translations_name
        self.addon.description = translations_description
        self.addon.save()
        extracted = self._extract()
        assert extracted['name_translations'] == [
            {'lang': 'en-US', 'string': translations_name['en-US']},
            {'lang': 'es-ES', 'string': translations_name['es-ES']},
        ]
        assert extracted['description_translations'] == [
            {'lang': 'en-US', 'string': translations_description['en-US']},
            {'lang': 'es-ES', 'string': translations_description['es-ES']},
            {'lang': 'it', 'string': '&lt;script&gt;alert(42)&lt;/script&gt;'},
        ]
        assert extracted['name_l10n_en-us'] == translations_name['en-US']
        assert extracted['name_l10n_en-gb'] == ''
        assert extracted['name_l10n_es-es'] == translations_name['es-ES']
        assert extracted['name_l10n_it'] == ''
        assert extracted['description_l10n_en-us'] == translations_description['en-US']
        assert extracted['description_l10n_es-es'] == translations_description['es-ES']
        assert extracted['description_l10n_fr'] == ''
        assert (
            extracted['description_l10n_it'] == '&lt;script&gt;alert(42)&lt;/script&gt;'
        )
        assert extracted['summary_l10n_en-us'] == ''
        # The non-l10n fields are fallbacks in the addon's default locale, they
        # need to always contain a string.
        assert extracted['name'] == 'Name in ënglish'
        assert extracted['summary'] == ''

    def test_extract_translations_engb_default(self):
        """Make sure we do correctly extract things for en-GB default locale"""
        with self.activate('en-GB'):
            kwargs = {
                'status': amo.STATUS_APPROVED,
                'type': amo.ADDON_EXTENSION,
                'default_locale': 'en-GB',
                'name': 'Banana Bonkers',
                'description': 'Let your browser eat your bananas',
                'summary': 'Banana Summary',
            }

            self.addon = Addon.objects.create(**kwargs)
            self.addon.name = {'es-ES': 'Banana Bonkers espanole'}
            self.addon.description = {
                'es-ES': 'Deje que su navegador coma sus plátanos'
            }
            self.addon.summary = {'es-ES': 'resumen banana'}
            self.addon.save()

        extracted = self._extract()

        assert extracted['name_translations'] == [
            {'lang': 'en-GB', 'string': 'Banana Bonkers'},
            {'lang': 'es-ES', 'string': 'Banana Bonkers espanole'},
        ]
        assert extracted['description_translations'] == [
            {'lang': 'en-GB', 'string': 'Let your browser eat your bananas'},
            {'lang': 'es-ES', 'string': 'Deje que su navegador coma sus plátanos'},
        ]
        assert extracted['name_l10n_en-gb'] == 'Banana Bonkers'
        assert extracted['name_l10n_en-us'] == ''
        assert extracted['name_l10n_es-es'] == 'Banana Bonkers espanole'
        assert (
            extracted['description_l10n_en-gb'] == 'Let your browser eat your bananas'
        )
        assert (
            extracted['description_l10n_es-es']
            == 'Deje que su navegador coma sus plátanos'
        )

    def test_extract_previews(self):
        second_preview = Preview.objects.create(
            addon=self.addon,
            position=2,
            caption={'en-US': 'My câption', 'fr': 'Mön tîtré'},
            sizes={'thumbnail': [199, 99], 'image': [567, 780]},
        )
        first_preview = Preview.objects.create(addon=self.addon, position=1)
        first_preview.reload()
        second_preview.reload()
        extracted = self._extract()
        assert extracted['previews']
        assert len(extracted['previews']) == 2
        assert extracted['previews'][0]['id'] == first_preview.pk
        assert extracted['previews'][0]['modified'] == first_preview.modified
        assert extracted['previews'][0]['caption_translations'] == []
        assert extracted['previews'][0]['sizes'] == first_preview.sizes == {}
        assert extracted['previews'][0]['position'] == first_preview.position
        assert extracted['previews'][1]['id'] == second_preview.pk
        assert extracted['previews'][1]['modified'] == second_preview.modified
        assert extracted['previews'][1]['caption_translations'] == [
            {'lang': 'en-US', 'string': 'My câption'},
            {'lang': 'fr', 'string': 'Mön tîtré'},
        ]
        assert (
            extracted['previews'][1]['sizes']
            == second_preview.sizes
            == {'thumbnail': [199, 99], 'image': [567, 780]}
        )
        assert extracted['previews'][1]['position'] == second_preview.position

        # Only raw translations dict should exist, since we don't need the
        # to search against preview captions.
        assert 'caption' not in extracted['previews'][0]
        assert 'caption' not in extracted['previews'][1]

    def test_extract_previews_statictheme(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        current_preview = VersionPreview.objects.create(
            version=self.addon.current_version,
            colors=[{'h': 1, 's': 2, 'l': 3, 'ratio': 0.9}],
            sizes={'thumbnail': [56, 78], 'image': [91, 234]},
            position=1,
        )
        second_preview = VersionPreview.objects.create(
            version=self.addon.current_version,
            sizes={'thumbnail': [12, 34], 'image': [56, 78]},
            position=2,
        )
        extracted = self._extract()
        assert extracted['previews']
        assert len(extracted['previews']) == 2
        assert 'caption_translations' not in extracted['previews'][0]
        assert extracted['previews'][0]['id'] == current_preview.pk
        assert extracted['previews'][0]['modified'] == current_preview.modified
        assert (
            extracted['previews'][0]['sizes']
            == current_preview.sizes
            == {'thumbnail': [56, 78], 'image': [91, 234]}
        )
        assert extracted['previews'][0]['position'] == current_preview.position
        assert 'caption_translations' not in extracted['previews'][1]
        assert extracted['previews'][1]['id'] == second_preview.pk
        assert extracted['previews'][1]['modified'] == second_preview.modified
        assert (
            extracted['previews'][1]['sizes']
            == second_preview.sizes
            == {'thumbnail': [12, 34], 'image': [56, 78]}
        )
        assert extracted['previews'][1]['position'] == second_preview.position

        # Make sure we extract colors from the first preview.
        assert extracted['colors'] == [{'h': 1, 's': 2, 'l': 3, 'ratio': 0.9}]

    def test_extract_staticthemes_somehow_no_previews(self):
        # Extracting a static theme with no previews should not fail.
        self.addon.update(type=amo.ADDON_STATICTHEME)

        extracted = self._extract()
        assert extracted['id'] == self.addon.pk
        assert extracted['previews'] == []
        assert extracted['colors'] is None

    def test_extract_promoted(self):
        # Non-promoted returns None.
        extracted = self._extract()
        assert not extracted['promoted']
        assert extracted['is_recommended'] is False

        # Promoted extension.
        self.addon = addon_factory(promoted_id=PROMOTED_GROUP_CHOICES.RECOMMENDED)
        extracted = self._extract()

        assert extracted['promoted'][0]
        assert (
            extracted['promoted'][0]['group_id'] == PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        assert extracted['promoted'][0]['approved_for_apps'] == [
            amo.FIREFOX.id,
            amo.ANDROID.id,
        ]
        assert extracted['is_recommended'] is True

        # Specific application.
        PromotedApproval.objects.filter(
            version=self.addon.current_version, application_id=amo.ANDROID.id
        ).delete()
        extracted = self._extract()
        assert extracted['promoted'][0]['approved_for_apps'] == [amo.FIREFOX.id]
        assert extracted['is_recommended'] is True

        # With multiple promotions
        self.make_addon_promoted(
            addon=self.addon,
            group_id=PROMOTED_GROUP_CHOICES.LINE,
            apps=[amo.FIREFOX],
        )
        self.addon.approve_for_version()
        extracted = self._extract()
        assert extracted['promoted']
        assert (
            extracted['promoted'][0]['group_id'] == PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        assert extracted['promoted'][1]['group_id'] == PROMOTED_GROUP_CHOICES.LINE

        # Promoted theme.
        self.addon = addon_factory(type=amo.ADDON_STATICTHEME)
        featured_collection, _ = Collection.objects.get_or_create(
            id=settings.COLLECTION_FEATURED_THEMES_ID
        )
        featured_collection.add_addon(self.addon)
        extracted = self._extract()
        assert extracted['promoted'][0]
        assert (
            extracted['promoted'][0]['group_id'] == PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        assert extracted['promoted'][0]['approved_for_apps'] == [
            amo.FIREFOX.id,
            amo.ANDROID.id,
        ]
        assert extracted['is_recommended'] is True

    @mock.patch('olympia.addons.indexers.create_chunked_tasks_signatures')
    def test_reindex_tasks_group(self, create_chunked_tasks_signatures_mock):
        from olympia.addons.tasks import index_addons

        expected_ids = [
            self.addon.pk,
            addon_factory(status=amo.STATUS_DELETED).pk,
            addon_factory(
                status=amo.STATUS_NULL,
                version_kw={'channel': amo.CHANNEL_UNLISTED},
            ).pk,
        ]
        rval = AddonIndexer.reindex_tasks_group('addons-1234567890')
        assert create_chunked_tasks_signatures_mock.call_count == 1
        assert create_chunked_tasks_signatures_mock.call_args[0] == (
            index_addons,
            expected_ids,
            150,
        )
        assert create_chunked_tasks_signatures_mock.call_args[1] == {
            'task_kwargs': {'index': 'addons-1234567890'},
        }
        assert rval == create_chunked_tasks_signatures_mock.return_value


class TestAddonIndexerWithES(ESTestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def test_mapping(self):
        """Compare actual mapping in ES with the one the indexer returns, once
        an object has been indexed.

        We don't want dynamic mapping for addons (too risky), so the two
        mappings should be equal."""
        self.reindex(Addon)

        indexer = AddonIndexer()
        real_index_name = self.get_index_name('default')
        alias = indexer.get_index_alias()
        mappings = self.es.indices.get_mapping(index=alias)[real_index_name]['mappings']

        actual_properties = mappings['properties']
        indexer_properties = indexer.get_mapping()['properties']
        assert set(actual_properties.keys()) == set(indexer_properties.keys())
