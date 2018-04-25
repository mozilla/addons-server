# -*- coding: utf-8 -*-
from itertools import chain

from olympia import amo
from olympia.addons.indexers import AddonIndexer
from olympia.addons.models import (
    Addon, Preview, attach_tags, attach_translations)
from olympia.amo.models import SearchMixin
from olympia.amo.tests import (
    ESTestCase, TestCase, addon_factory, collection_factory, file_factory,
    version_factory)
from olympia.bandwagon.models import FeaturedCollection
from olympia.constants.applications import FIREFOX
from olympia.constants.platforms import PLATFORM_ALL, PLATFORM_MAC
from olympia.constants.search import SEARCH_ANALYZER_MAP
from olympia.files.models import WebextPermission
from olympia.versions.models import VersionPreview


class TestAddonIndexer(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    # The base list of fields we expect to see in the mapping/extraction.
    # This only contains the fields for which we use the value directly,
    # see expected_fields() for the rest.
    simple_fields = [
        'average_daily_users', 'bayesian_rating', 'contributions', 'created',
        'default_locale', 'guid', 'hotness', 'icon_hash', 'icon_type', 'id',
        'is_disabled', 'is_experimental', 'last_updated', 'modified',
        'public_stats', 'requires_payment', 'slug', 'status', 'type',
        'view_source', 'weekly_downloads',
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
            'app', 'boost', 'category',
            'current_version', 'description', 'featured_for',
            'has_eula', 'has_privacy_policy',
            'has_theme_rereview', 'is_featured', 'latest_unlisted_version',
            'listed_authors', 'name', 'platforms', 'previews',
            'public_stats', 'ratings', 'summary', 'tags',
        ]

        # Fields that need to be present in the mapping, but might be skipped
        # for extraction because they can be null.
        nullable_fields = ['persona']

        # For each translated field that needs to be indexed, we store one
        # version for each language-specific analyzer we have.
        _indexed_translated_fields = ('name', 'description', 'summary')
        analyzer_fields = list(chain.from_iterable(
            [['%s_l10n_%s' % (field, analyzer) for analyzer
             in SEARCH_ANALYZER_MAP] for field in _indexed_translated_fields]))

        # It'd be annoying to hardcode `analyzer_fields`, so we generate it,
        # but to make sure the test is correct we still do a simple check of
        # the length to make sure we properly flattened the list.
        assert len(analyzer_fields) == (len(SEARCH_ANALYZER_MAP) *
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

        # Make sure nothing inside 'persona' is indexed, it's only there to be
        # returned back to the API directly.
        for field in mapping_properties['persona']['properties'].values():
            assert field['index'] is False

        # Make sure current_version mapping is set.
        assert mapping_properties['current_version']['properties']
        version_mapping = mapping_properties['current_version']['properties']
        expected_version_keys = (
            'id', 'compatible_apps', 'files', 'reviewed', 'version')
        assert set(version_mapping.keys()) == set(expected_version_keys)

        # Make sure files mapping is set inside current_version.
        files_mapping = version_mapping['files']['properties']
        expected_file_keys = (
            'id', 'created', 'filename', 'hash', 'is_webextension',
            'is_restart_required', 'is_mozilla_signed_extension', 'platform',
            'size', 'status', 'strict_compatibility',
            'webext_permissions_list')
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
        qs = Addon.unfiltered.filter(id__in=[self.addon.pk]).no_cache()
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
        assert extracted['has_theme_rereview'] is None
        assert extracted['latest_unlisted_version'] is None
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
        assert extracted['is_featured'] is False

    def test_extract_is_featured(self):
        collection = collection_factory()
        FeaturedCollection.objects.create(collection=collection,
                                          application=collection.application)
        collection.add_addon(self.addon)
        assert self.addon.is_featured()
        extracted = self._extract()
        assert extracted['is_featured'] is True

    def test_extract_featured_for(self):
        collection = collection_factory()
        FeaturedCollection.objects.create(collection=collection,
                                          application=amo.FIREFOX.id)
        collection.add_addon(self.addon)
        extracted = self._extract()
        assert extracted['featured_for'] == [
            {'application': [amo.FIREFOX.id], 'locales': [None]}]

        collection = collection_factory()
        FeaturedCollection.objects.create(collection=collection,
                                          application=amo.FIREFOX.id,
                                          locale='fr')
        collection.add_addon(self.addon)
        extracted = self._extract()
        assert extracted['featured_for'] == [
            {'application': [amo.FIREFOX.id], 'locales': [None, 'fr']}]

        collection = collection_factory()
        FeaturedCollection.objects.create(collection=collection,
                                          application=amo.ANDROID.id,
                                          locale='de-DE')
        collection.add_addon(self.addon)
        extracted = self._extract()
        assert extracted['featured_for'] == [
            {'application': [amo.FIREFOX.id], 'locales': [None, 'fr']},
            {'application': [amo.ANDROID.id], 'locales': ['de-DE']}]

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
        version = self.addon.current_version
        file_factory(version=version, platform=PLATFORM_MAC.id)

        unlisted_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED, file_kw={
                'is_webextension': True,
            })
        # Give one of the versions some webext permissions to test that.
        WebextPermission.objects.create(
            file=unlisted_version.all_files[0],
            permissions=['bookmarks', 'random permission']
        )
        extracted = self._extract()

        assert extracted['current_version']
        assert extracted['current_version']['id'] == version.pk
        # Because strict_compatibility is False, the max version we record in
        # the index is an arbitrary super high version.
        assert extracted['current_version']['compatible_apps'] == {
            FIREFOX.id: {
                'min': 2000000200100L,
                'max': 9999000000200100,
                'max_human': '4.0',
                'min_human': '2.0',
            }
        }
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
            assert extracted_file['webext_permissions_list'] == []

        assert set(extracted['platforms']) == set([PLATFORM_MAC.id,
                                                   PLATFORM_ALL.id])

        version = unlisted_version
        assert extracted['latest_unlisted_version']
        assert extracted['latest_unlisted_version']['id'] == version.pk
        # Because strict_compatibility is False, the max version we record in
        # the index is an arbitrary super high version.
        assert extracted['latest_unlisted_version']['compatible_apps'] == {
            FIREFOX.id: {
                'min': 4009900200100L,
                'max': 9999000000200100,
                'max_human': '5.0.99',
                'min_human': '4.0.99',
            }
        }
        assert (
            extracted['latest_unlisted_version']['version'] == version.version)
        for idx, file_ in enumerate(version.all_files):
            extracted_file = extracted['latest_unlisted_version']['files'][idx]
            assert extracted_file['id'] == file_.pk
            assert extracted_file['created'] == file_.created
            assert extracted_file['filename'] == file_.filename
            assert extracted_file['hash'] == file_.hash
            assert extracted_file['is_webextension'] == file_.is_webextension
            assert extracted_file['is_mozilla_signed_extension'] == (
                file_.is_mozilla_signed_extension)
            assert extracted_file['is_restart_required'] == (
                file_.is_restart_required)
            assert extracted_file['platform'] == file_.platform
            assert extracted_file['size'] == file_.size
            assert extracted_file['status'] == file_.status
            assert (extracted_file['webext_permissions_list'] ==
                    file_.webext_permissions_list ==
                    ['bookmarks', 'random permission'])

    def test_version_compatibility_with_strict_compatibility_enabled(self):
        version = self.addon.current_version
        file_factory(
            version=version, platform=PLATFORM_MAC.id,
            strict_compatibility=True)
        extracted = self._extract()

        assert extracted['current_version']['compatible_apps'] == {
            FIREFOX.id: {
                'min': 2000000200100L,
                'max': 4000000200100L,
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
        self.addon.name = translations_name
        self.addon.description = translations_description
        self.addon.save()
        extracted = self._extract()
        assert sorted(extracted['name_translations']) == sorted([
            {'lang': u'en-US', 'string': translations_name['en-US']},
            {'lang': u'es', 'string': translations_name['es']},
        ])
        assert sorted(extracted['description_translations']) == sorted([
            {'lang': u'en-US', 'string': translations_description['en-US']},
            {'lang': u'es', 'string': translations_description['es']},
            {'lang': u'it', 'string': '&lt;script&gt;alert(42)&lt;/script&gt;'}
        ])
        assert extracted['name_l10n_english'] == [translations_name['en-US']]
        assert extracted['name_l10n_spanish'] == [translations_name['es']]
        assert (extracted['description_l10n_english'] ==
                [translations_description['en-US']])
        assert (extracted['description_l10n_spanish'] ==
                [translations_description['es']])
        assert (extracted['description_l10n_italian'] ==
                ['&lt;script&gt;alert(42)&lt;/script&gt;'])

    def test_extract_translations_engb_default(self):
        """Make sure we do correctly extract things for en-GB default locale"""
        with self.activate('en-GB'):
            kwargs = {
                'status': amo.STATUS_PUBLIC,
                'type': amo.ADDON_EXTENSION,
                'default_locale': 'en-GB',
                'name': 'Banana Bonkers',
                'description': u'Let your browser eat your bananas',
                'summary': u'Banana Summary',
            }

            self.addon = Addon.objects.create(**kwargs)
            self.addon.name = {'es': u'Banana Bonkers espanole'}
            self.addon.description = {
                'es': u'Deje que su navegador coma sus plátanos'}
            self.addon.summary = {'es': u'resumen banana'}
            self.addon.save()

        extracted = self._extract()

        assert sorted(extracted['name_translations']) == sorted([
            {'lang': u'en-GB', 'string': 'Banana Bonkers'},
            {'lang': u'es', 'string': u'Banana Bonkers espanole'},
        ])
        assert sorted(extracted['description_translations']) == sorted([
            {'lang': u'en-GB', 'string': u'Let your browser eat your bananas'},
            {
                'lang': u'es',
                'string': u'Deje que su navegador coma sus plátanos'
            },
        ])
        assert extracted['name_l10n_english'] == ['Banana Bonkers']
        assert extracted['name_l10n_spanish'] == [u'Banana Bonkers espanole']
        assert (extracted['description_l10n_english'] ==
                [u'Let your browser eat your bananas'])
        assert (extracted['description_l10n_spanish'] ==
                [u'Deje que su navegador coma sus plátanos'])

    def test_extract_persona(self):
        # Override self.addon with a persona.
        self.addon = addon_factory(persona_id=42, type=amo.ADDON_PERSONA)
        # It's a Persona, there should not be any files attached, and the
        # indexer should not care.
        assert self.addon.current_version.files.count() == 0

        persona = self.addon.persona
        persona.header = u'myheader.jpg'
        persona.footer = u'myfooter.jpg'
        persona.accentcolor = u'336699'
        persona.textcolor = u'f0f0f0'
        persona.author = u'Me-me-me-Myself'
        persona.display_username = u'my-username'
        persona.popularity = 1000
        persona.save()
        extracted = self._extract()
        assert extracted['average_daily_users'] == persona.popularity
        assert extracted['weekly_downloads'] == persona.popularity * 7
        assert extracted['boost'] == float(persona.popularity ** .2) * 4
        assert extracted['has_theme_rereview'] is False
        assert extracted['persona']['accentcolor'] == persona.accentcolor
        # We need the author that will go in theme_data here, which is
        # persona.display_username, not persona.author.
        assert extracted['persona']['author'] == persona.display_username
        assert extracted['persona']['header'] == persona.header
        assert extracted['persona']['footer'] == persona.footer
        assert extracted['persona']['is_new'] is False  # It has a persona_id.
        assert extracted['persona']['textcolor'] == persona.textcolor

        # Personas are always considered compatible with every platform, and
        # almost all versions of all apps.
        assert extracted['platforms'] == [amo.PLATFORM_ALL.id]
        assert extracted['current_version']['compatible_apps'] == {
            amo.ANDROID.id: {
                'max': 9999000000200100,
                'max_human': '9999',
                'min': 11000000200100,
                'min_human': '11.0',
            },
            amo.FIREFOX.id: {
                'max': 9999000000200100,
                'max_human': '9999',
                'min': 4000000200100,
                'min_human': '4.0',
            },
            amo.THUNDERBIRD.id: {
                'max': 9999000000200100,
                'max_human': '9999',
                'min': 5000000200100,
                'min_human': '5.0',
            },
            amo.SEAMONKEY.id: {
                'max': 9999000000200100,
                'max_human': '9999',
                'min': 2010000200100,
                'min_human': '2.1',
            },
        }
        self.addon = addon_factory(persona_id=0, type=amo.ADDON_PERSONA)
        extracted = self._extract()
        assert extracted['persona']['is_new'] is True  # No persona_id.

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
            sizes={'thumbnail': [56, 78], 'image': [91, 234]})
        extracted = self._extract()
        assert extracted['previews']
        assert len(extracted['previews']) == 1
        assert 'caption_translations' not in extracted['previews'][0]
        assert extracted['previews'][0]['id'] == current_preview.pk
        assert extracted['previews'][0]['modified'] == current_preview.modified
        assert extracted['previews'][0]['sizes'] == current_preview.sizes == {
            'thumbnail': [56, 78], 'image': [91, 234]}


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
