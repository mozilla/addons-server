# -*- coding: utf-8 -*-
from itertools import chain
from unittest import mock

from olympia import amo
from olympia.addons.indexers import AddonIndexer
from olympia.addons.models import (
    Addon, Preview, attach_tags, attach_translations)
from olympia.amo.models import SearchMixin
from olympia.amo.tests import addon_factory, ESTestCase, TestCase, file_factory
from olympia.constants.applications import FIREFOX
from olympia.constants.platforms import PLATFORM_ALL, PLATFORM_MAC
from olympia.constants.search import SEARCH_LANGUAGE_TO_ANALYZER
from olympia.files.models import WebextPermission
from olympia.versions.compare import version_int
from olympia.versions.models import License, VersionPreview


class TestAddonIndexer(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    # The base list of fields we expect to see in the mapping/extraction.
    # This only contains the fields for which we use the value directly,
    # see expected_fields() for the rest.
    simple_fields = [
        'average_daily_users', 'bayesian_rating', 'contributions', 'created',
        'default_locale', 'guid', 'hotness', 'icon_hash', 'icon_type', 'id',
        'is_disabled', 'is_experimental', 'is_recommended', 'last_updated',
        'modified', 'requires_payment', 'slug', 'status', 'type',
        'weekly_downloads',
    ]

    def setUp(self):
        super(TestAddonIndexer, self).setUp()
        self.transforms = (attach_tags, attach_translations)
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
            'app', 'boost', 'category', 'colors', 'current_version',
            'description', 'has_eula', 'has_privacy_policy', 'listed_authors',
            'name', 'platforms', 'previews', 'ratings', 'summary', 'tags',
        ]

        # Fields that need to be present in the mapping, but might be skipped
        # for extraction because they can be null.
        nullable_fields = []

        # For each translated field that needs to be indexed, we store one
        # version for each language we have an analyzer for.
        _indexed_translated_fields = ('name', 'description', 'summary')
        analyzer_fields = list(chain.from_iterable(
            [['%s_l10n_%s' % (field, lang) for lang, analyzer
             in SEARCH_LANGUAGE_TO_ANALYZER.items()]
             for field in _indexed_translated_fields]))

        # It'd be annoying to hardcode `analyzer_fields`, so we generate it,
        # but to make sure the test is correct we still do a simple check of
        # the length to make sure we properly flattened the list.
        assert len(analyzer_fields) == (len(SEARCH_LANGUAGE_TO_ANALYZER) *
                                        len(_indexed_translated_fields))

        # Each translated field that we want to return to the API.
        raw_translated_fields = [
            '%s_translations' % field for field in
            ['name', 'description', 'developer_comments', 'homepage',
             'summary', 'support_email', 'support_url']]

        # Return a list with the base fields and the dynamic ones added.
        fields = (cls.simple_fields + complex_fields + analyzer_fields +
                  raw_translated_fields)
        if include_nullable:
            fields += nullable_fields
        return fields

    def test_mapping(self):
        doc_name = self.indexer.get_doctype_name()
        assert doc_name

        mapping_properties = self.indexer.get_mapping()[doc_name]['properties']

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
            'id', 'compatible_apps', 'files', 'license',
            'release_notes_translations', 'reviewed', 'version')
        assert set(version_mapping.keys()) == set(expected_version_keys)

        # Make sure files mapping is set inside current_version.
        files_mapping = version_mapping['files']['properties']
        expected_file_keys = (
            'id', 'created', 'filename', 'hash', 'is_webextension',
            'is_restart_required', 'is_mozilla_signed_extension', 'platform',
            'size', 'status', 'strict_compatibility',
            'permissions', 'optional_permissions')
        assert set(files_mapping.keys()) == set(expected_file_keys)

    def test_index_setting_boolean(self):
        """Make sure that the `index` setting is a true/false boolean.

        Old versions of ElasticSearch allowed 'no' and 'yes' strings,
        this changed with ElasticSearch 5.x.
        """
        doc_name = self.indexer.get_doctype_name()
        assert doc_name

        mapping_properties = self.indexer.get_mapping()[doc_name]['properties']

        assert all(
            isinstance(prop['index'], bool)
            for prop in mapping_properties.values()
            if 'index' in prop)

        # Make sure our version_mapping is setup correctly too.
        props = mapping_properties['current_version']['properties']

        assert all(
            isinstance(prop['index'], bool)
            for prop in props.values() if 'index' in prop)

        # As well as for current_version.files
        assert all(
            isinstance(prop['index'], bool)
            for prop in props['files']['properties'].values()
            if 'index' in prop)

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
            self.expected_fields(include_nullable=False))

        # Check base fields values. Other tests below check the dynamic ones.
        for field_name in self.simple_fields:
            assert extracted[field_name] == getattr(self.addon, field_name)

        assert extracted['app'] == [FIREFOX.id]
        assert extracted['boost'] == self.addon.average_daily_users ** .2 * 4
        assert extracted['category'] == [1, 22, 71]  # From fixture.
        assert extracted['current_version']
        assert extracted['listed_authors'] == [
            {'name': u'55021 التطب', 'id': 55021, 'username': '55021',
             'is_public': True}]
        assert extracted['platforms'] == [PLATFORM_ALL.id]
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
        version = self.addon.current_version
        # Make the version a webextension and add a bunch of things to it to
        # test different scenarios.
        version.all_files[0].update(is_webextension=True)
        file_factory(
            version=version, platform=PLATFORM_MAC.id, is_webextension=True)
        del version.all_files
        version.license = License.objects.create(
            name=u'My licensé',
            url='http://example.com/',
            builtin=0)
        [WebextPermission.objects.create(
            file=file_, permissions=permissions,
            optional_permissions=optional_permissions
        ) for file_ in version.all_files]
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
            'builtin': 0,
            'id': version.license.pk,
            'name_translations': [{'lang': u'en-US', 'string': u'My licensé'}],
            'url': u'http://example.com/'
        }
        assert extracted['current_version']['release_notes_translations'] == [
            {'lang': 'en-US', 'string': u'Fix for an important bug'},
            {'lang': 'fr', 'string': u"Quelque chose en fran\xe7ais."
                                     u"\n\nQuelque chose d'autre."},
        ]
        assert extracted['current_version']['reviewed'] == version.reviewed
        assert extracted['current_version']['version'] == version.version
        for index, file_ in enumerate(version.all_files):
            extracted_file = extracted['current_version']['files'][index]
            assert extracted_file['id'] == file_.pk
            assert extracted_file['created'] == file_.created
            assert extracted_file['filename'] == file_.filename
            assert extracted_file['hash'] == file_.hash
            assert extracted_file['is_webextension'] == file_.is_webextension
            assert extracted_file['is_restart_required'] == (
                file_.is_restart_required)
            assert extracted_file['is_mozilla_signed_extension'] == (
                file_.is_mozilla_signed_extension)
            assert extracted_file['platform'] == file_.platform
            assert extracted_file['size'] == file_.size
            assert extracted_file['status'] == file_.status
            assert (
                extracted_file['permissions'] ==
                permissions)
            assert (
                extracted_file['optional_permissions'] ==
                optional_permissions)

        assert set(extracted['platforms']) == set([PLATFORM_MAC.id,
                                                   PLATFORM_ALL.id])

    def test_version_compatibility_with_strict_compatibility_enabled(self):
        version = self.addon.current_version
        file_factory(
            version=version, platform=PLATFORM_MAC.id,
            strict_compatibility=True)
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
            'en-US': u'Name in ënglish',
            'es': u'Name in Español',
            'it': None,  # Empty name should be ignored in extract.
        }
        translations_description = {
            'en-US': u'Description in ënglish',
            'es': u'Description in Español',
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
            {'lang': 'es', 'string': translations_name['es']},
        ]
        assert extracted['description_translations'] == [
            {'lang': 'en-US', 'string': translations_description['en-US']},
            {'lang': 'es', 'string': translations_description['es']},
            {'lang': 'it', 'string': '&lt;script&gt;alert(42)&lt;/script&gt;'}
        ]
        assert extracted['name_l10n_en-us'] == translations_name['en-US']
        assert extracted['name_l10n_en-gb'] == ''
        assert extracted['name_l10n_es'] == translations_name['es']
        assert extracted['name_l10n_it'] == ''
        assert (
            extracted['description_l10n_en-us'] ==
            translations_description['en-US']
        )
        assert (
            extracted['description_l10n_es'] ==
            translations_description['es']
        )
        assert extracted['description_l10n_fr'] == ''
        assert (
            extracted['description_l10n_it'] ==
            '&lt;script&gt;alert(42)&lt;/script&gt;'
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
            self.addon.name = {'es': 'Banana Bonkers espanole'}
            self.addon.description = {
                'es': 'Deje que su navegador coma sus plátanos'}
            self.addon.summary = {'es': 'resumen banana'}
            self.addon.save()

        extracted = self._extract()

        assert extracted['name_translations'] == [
            {'lang': 'en-GB', 'string': 'Banana Bonkers'},
            {'lang': 'es', 'string': 'Banana Bonkers espanole'},
        ]
        assert extracted['description_translations'] == [
            {'lang': 'en-GB', 'string': 'Let your browser eat your bananas'},
            {
                'lang': 'es',
                'string': 'Deje que su navegador coma sus plátanos'
            },
        ]
        assert extracted['name_l10n_en-gb'] == 'Banana Bonkers'
        assert extracted['name_l10n_en-us'] == ''
        assert extracted['name_l10n_es'] == 'Banana Bonkers espanole'
        assert (
            extracted['description_l10n_en-gb'] ==
            'Let your browser eat your bananas'
        )
        assert (
            extracted['description_l10n_es'] ==
            'Deje que su navegador coma sus plátanos'
        )

    def test_extract_previews(self):
        second_preview = Preview.objects.create(
            addon=self.addon, position=2,
            caption={'en-US': u'My câption', 'fr': u'Mön tîtré'},
            sizes={'thumbnail': [199, 99], 'image': [567, 780]})
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
        assert extracted['previews'][1]['id'] == second_preview.pk
        assert extracted['previews'][1]['modified'] == second_preview.modified
        assert extracted['previews'][1]['caption_translations'] == [
            {'lang': 'en-US', 'string': u'My câption'},
            {'lang': 'fr', 'string': u'Mön tîtré'}]
        assert extracted['previews'][1]['sizes'] == second_preview.sizes == {
            'thumbnail': [199, 99], 'image': [567, 780]}

        # Only raw translations dict should exist, since we don't need the
        # to search against preview captions.
        assert 'caption' not in extracted['previews'][0]
        assert 'caption' not in extracted['previews'][1]

    def test_extract_previews_statictheme(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        current_preview = VersionPreview.objects.create(
            version=self.addon.current_version,
            colors=[{'h': 1, 's': 2, 'l': 3, 'ratio': 0.9}],
            sizes={'thumbnail': [56, 78], 'image': [91, 234]}, position=1)
        second_preview = VersionPreview.objects.create(
            version=self.addon.current_version,
            sizes={'thumbnail': [12, 34], 'image': [56, 78]}, position=2)
        extracted = self._extract()
        assert extracted['previews']
        assert len(extracted['previews']) == 2
        assert 'caption_translations' not in extracted['previews'][0]
        assert extracted['previews'][0]['id'] == current_preview.pk
        assert extracted['previews'][0]['modified'] == current_preview.modified
        assert extracted['previews'][0]['sizes'] == current_preview.sizes == {
            'thumbnail': [56, 78], 'image': [91, 234]}
        assert 'caption_translations' not in extracted['previews'][1]
        assert extracted['previews'][1]['id'] == second_preview.pk
        assert extracted['previews'][1]['modified'] == second_preview.modified
        assert extracted['previews'][1]['sizes'] == second_preview.sizes == {
            'thumbnail': [12, 34], 'image': [56, 78]}

        # Make sure we extract colors from the first preview.
        assert extracted['colors'] == [{'h': 1, 's': 2, 'l': 3, 'ratio': 0.9}]

    def test_extract_staticthemes_somehow_no_previews(self):
        # Extracting a static theme with no previews should not fail.
        self.addon.update(type=amo.ADDON_STATICTHEME)

        extracted = self._extract()
        assert extracted['id'] == self.addon.pk
        assert extracted['previews'] == []
        assert extracted['colors'] is None

    @mock.patch('olympia.addons.indexers.create_chunked_tasks_signatures')
    def test_reindex_tasks_group(self, create_chunked_tasks_signatures_mock):
        from olympia.addons.tasks import index_addons

        expected_ids = [
            self.addon.pk,
            addon_factory(status=amo.STATUS_DELETED).pk,
            addon_factory(
                status=amo.STATUS_NULL,
                version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED}).pk,
        ]
        rval = AddonIndexer.reindex_tasks_group('addons')
        assert create_chunked_tasks_signatures_mock.call_count == 1
        assert create_chunked_tasks_signatures_mock.call_args[0] == (
            index_addons, expected_ids, 150
        )
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
        doc_name = indexer.get_doctype_name()
        real_index_name = self.get_index_name(SearchMixin.ES_ALIAS_KEY)
        mappings = self.es.indices.get_mapping(
            indexer.get_index_alias())[real_index_name]['mappings']

        actual_properties = mappings[doc_name]['properties']
        indexer_properties = indexer.get_mapping()[doc_name]['properties']

        assert set(actual_properties.keys()) == set(indexer_properties.keys())
