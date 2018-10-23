# -*- coding: utf-8 -*-
import json
import mock
import os
import pytest
import tempfile
import zipfile

from django.conf import settings
from django.forms import ValidationError

from olympia import amo
from olympia.addons.models import Category
from olympia.addons.utils import (
    build_static_theme_xpi_from_lwt, build_webext_dictionary_from_legacy,
    get_addon_recommendations, get_addon_recommendations_invalid,
    get_creatured_ids, get_featured_ids, is_outcome_recommended,
    TAAR_LITE_FALLBACK_REASON_EMPTY, TAAR_LITE_FALLBACK_REASON_TIMEOUT,
    TAAR_LITE_FALLBACKS, TAAR_LITE_OUTCOME_CURATED,
    TAAR_LITE_OUTCOME_REAL_FAIL, TAAR_LITE_OUTCOME_REAL_SUCCESS,
    TAAR_LITE_FALLBACK_REASON_INVALID,
    verify_mozilla_trademark)
from olympia.amo.tests import (
    AMOPaths, TestCase, addon_factory, collection_factory, user_factory)
from olympia.bandwagon.models import FeaturedCollection
from olympia.constants.categories import CATEGORIES_BY_ID


@pytest.mark.django_db
@pytest.mark.parametrize('name, allowed, email', (
    # Regular name, obviously always allowed
    ('Fancy new Add-on', True, 'foo@bar.com'),
    # We allow the 'for ...' postfix to be used
    ('Fancy new Add-on for Firefox', True, 'foo@bar.com'),
    ('Fancy new Add-on for Mozilla', True, 'foo@bar.com'),
    # But only the postfix
    ('Fancy new Add-on for Firefox Browser', False, 'foo@bar.com'),
    ('For Firefox fancy new add-on', False, 'foo@bar.com'),
    # But users with @mozilla.com or @mozilla.org email addresses
    # are allowed
    ('Firefox makes everything better', False, 'bar@baz.com'),
    ('Firefox makes everything better', True, 'foo@mozilla.com'),
    ('Firefox makes everything better', True, 'foo@mozilla.org'),
    ('Mozilla makes everything better', True, 'foo@mozilla.com'),
    ('Mozilla makes everything better', True, 'foo@mozilla.org'),
    # A few more test-cases...
    ('Firefox add-on for Firefox', False, 'foo@bar.com'),
    ('Firefox add-on for Firefox', True, 'foo@mozilla.com'),
    ('Foobarfor Firefox', False, 'foo@bar.com'),
    ('Better Privacy for Firefox!', True, 'foo@bar.com'),
    ('Firefox awesome for Mozilla', False, 'foo@bar.com'),
    ('Firefox awesome for Mozilla', True, 'foo@mozilla.org'),
))
def test_verify_mozilla_trademark(name, allowed, email):
    user = user_factory(email=email)

    if not allowed:
        with pytest.raises(ValidationError) as exc:
            verify_mozilla_trademark(name, user)
        assert exc.value.message == (
            'Add-on names cannot contain the Mozilla or Firefox trademarks.'
        )
    else:
        verify_mozilla_trademark(name, user)


class TestGetFeaturedIds(TestCase):
    fixtures = ['addons/featured', 'bandwagon/featured_collections',
                'base/addon_3615', 'base/collections', 'base/featured',
                'base/users']

    no_locale = (1001, 1003, 2464, 7661, 15679)
    en_us_locale = (3481,)
    all_locales = no_locale + en_us_locale
    no_locale_type_one = (1001, 1003, 2464, 7661)

    def setUp(self):
        super(TestGetFeaturedIds, self).setUp()

    def test_by_app(self):
        assert set(get_featured_ids(amo.FIREFOX)) == (
            set(self.all_locales))

    def test_by_type(self):
        assert set(get_featured_ids(amo.FIREFOX, 'xx', 1)) == (
            set(self.no_locale_type_one))

    def test_by_locale(self):
        assert set(get_featured_ids(amo.FIREFOX)) == (
            set(self.all_locales))
        assert set(get_featured_ids(amo.FIREFOX, 'xx')) == (
            set(self.no_locale))
        assert set(get_featured_ids(amo.FIREFOX, 'en-US')) == (
            set(self.no_locale + self.en_us_locale))

    def test_locale_shuffle(self):
        # Make sure the locale-specific add-ons are at the front.
        ids = get_featured_ids(amo.FIREFOX, 'en-US')
        assert (ids[0],) == self.en_us_locale


class TestGetCreaturedIds(TestCase):
    fixtures = ['addons/featured', 'bandwagon/featured_collections',
                'base/addon_3615', 'base/collections', 'base/featured',
                'base/users']
    category_id = 22

    no_locale = (1001,)
    en_us_locale = (3481,)

    def setUp(self):
        super(TestGetCreaturedIds, self).setUp()

    def test_by_category_static(self):
        category = CATEGORIES_BY_ID[self.category_id]
        assert set(get_creatured_ids(category, None)) == (
            set(self.no_locale))

    def test_by_category_dynamic(self):
        category = Category.objects.get(pk=self.category_id)
        assert set(get_creatured_ids(category, None)) == (
            set(self.no_locale))

    def test_by_category_id(self):
        assert set(get_creatured_ids(self.category_id, None)) == (
            set(self.no_locale))

    def test_by_category_app(self):
        # Add an addon to the same category, but in a featured collection
        # for a different app: it should not be returned.
        extra_addon = addon_factory(
            category=Category.objects.get(pk=self.category_id))
        collection = collection_factory()
        collection.add_addon(extra_addon)
        FeaturedCollection.objects.create(
            application=amo.ANDROID.id, collection=collection)

        assert set(get_creatured_ids(self.category_id, None)) == (
            set(self.no_locale))

    def test_by_locale(self):
        assert set(get_creatured_ids(self.category_id, 'en-US')) == (
            set(self.no_locale + self.en_us_locale))

    def test_by_category_app_and_locale(self):
        # Add an addon to the same category and locale, but in a featured
        # collection for a different app: it should not be returned.
        extra_addon = addon_factory(
            category=Category.objects.get(pk=self.category_id))
        collection = collection_factory()
        collection.add_addon(extra_addon)
        FeaturedCollection.objects.create(
            application=amo.ANDROID.id, collection=collection,
            locale='en-US')

        assert set(get_creatured_ids(self.category_id, 'en-US')) == (
            set(self.no_locale + self.en_us_locale))

    def test_shuffle(self):
        ids = get_creatured_ids(self.category_id, 'en-US')
        assert (ids[0],) == self.en_us_locale


class TestGetAddonRecommendations(TestCase):
    def setUp(self):
        patcher = mock.patch(
            'olympia.addons.utils.call_recommendation_server')
        self.recommendation_server_mock = patcher.start()
        self.addCleanup(patcher.stop)
        self.a101 = addon_factory(id=101, guid='101@mozilla')
        addon_factory(id=102, guid='102@mozilla')
        addon_factory(id=103, guid='103@mozilla')
        addon_factory(id=104, guid='104@mozilla')

        self.recommendation_guids = [
            '101@mozilla', '102@mozilla', '103@mozilla', '104@mozilla'
        ]
        self.recommendation_server_mock.return_value = (
            self.recommendation_guids)

    def test_recommended(self):
        recommendations, outcome, reason = get_addon_recommendations(
            'a@b', True)
        assert recommendations == self.recommendation_guids
        assert outcome == TAAR_LITE_OUTCOME_REAL_SUCCESS
        assert reason is None

    def test_recommended_no_results(self):
        self.recommendation_server_mock.return_value = []
        recommendations, outcome, reason = get_addon_recommendations(
            'a@b', True)
        assert recommendations == TAAR_LITE_FALLBACKS
        assert outcome == TAAR_LITE_OUTCOME_REAL_FAIL
        assert reason is TAAR_LITE_FALLBACK_REASON_EMPTY

    def test_recommended_timeout(self):
        self.recommendation_server_mock.return_value = None
        recommendations, outcome, reason = get_addon_recommendations(
            'a@b', True)
        assert recommendations == TAAR_LITE_FALLBACKS
        assert outcome == TAAR_LITE_OUTCOME_REAL_FAIL
        assert reason is TAAR_LITE_FALLBACK_REASON_TIMEOUT

    def test_not_recommended(self):
        recommendations, outcome, reason = get_addon_recommendations(
            'a@b', False)
        assert not self.recommendation_server_mock.called
        assert recommendations == TAAR_LITE_FALLBACKS
        assert outcome == TAAR_LITE_OUTCOME_CURATED
        assert reason is None

    def test_invalid_fallback(self):
        recommendations, outcome, reason = get_addon_recommendations_invalid()
        assert recommendations == TAAR_LITE_FALLBACKS
        assert outcome == TAAR_LITE_OUTCOME_REAL_FAIL
        assert reason == TAAR_LITE_FALLBACK_REASON_INVALID

    def test_is_outcome_recommended(self):
        assert is_outcome_recommended(TAAR_LITE_OUTCOME_REAL_SUCCESS)
        assert not is_outcome_recommended(TAAR_LITE_OUTCOME_REAL_FAIL)
        assert not is_outcome_recommended(TAAR_LITE_OUTCOME_CURATED)


class TestBuildStaticThemeXpiFromLwt(TestCase):
    def setUp(self):
        self.background_png = os.path.join(
            settings.ROOT, 'src/olympia/versions/tests/static_themes/weta.png')

    def test_lwt(self):
        # Create our persona.
        lwt = addon_factory(
            type=amo.ADDON_PERSONA, persona_id=0, name=u'Amáze',
            description=u'It does all d£ things')
        lwt.persona.accentcolor, lwt.persona.textcolor = '123', '456789'
        # Give it a background header file.
        lwt.persona.header = 'weta.png'
        lwt.persona.header_path = self.background_png  # It's a cached_property

        static_xpi = tempfile.NamedTemporaryFile(suffix='.xpi').name
        build_static_theme_xpi_from_lwt(lwt, static_xpi)

        with zipfile.ZipFile(static_xpi, 'r', zipfile.ZIP_DEFLATED) as xpi:
            manifest = xpi.read('manifest.json')
            manifest_json = json.loads(manifest)
            assert manifest_json['name'] == u'Amáze'
            assert manifest_json['description'] == u'It does all d£ things'
            assert manifest_json['theme']['images']['headerURL'] == (
                u'weta.png')
            assert manifest_json['theme']['colors']['accentcolor'] == (
                u'#123')
            assert manifest_json['theme']['colors']['textcolor'] == (
                u'#456789')
            assert (xpi.read('weta.png') ==
                    open(self.background_png).read())

    def test_lwt_missing_info(self):
        # Create our persona.
        lwt = addon_factory(
            type=amo.ADDON_PERSONA, persona_id=0)
        lwt.update(name='')
        # Give it a background header file.
        lwt.persona.header = 'weta.png'
        lwt.persona.header_path = self.background_png  # It's a cached_property

        static_xpi = tempfile.NamedTemporaryFile(suffix='.xpi').name
        build_static_theme_xpi_from_lwt(lwt, static_xpi)

        with zipfile.ZipFile(static_xpi, 'r', zipfile.ZIP_DEFLATED) as xpi:
            manifest = xpi.read('manifest.json')
            manifest_json = json.loads(manifest)
            assert manifest_json['name'] == lwt.slug
            assert 'description' not in manifest_json.keys()
            assert manifest_json['theme']['images']['headerURL'] == (
                u'weta.png')
            assert manifest_json['theme']['colors']['accentcolor'] == (
                amo.THEME_ACCENTCOLOR_DEFAULT)
            assert manifest_json['theme']['colors']['textcolor'] == (
                u'#000')
            assert (xpi.read('weta.png') ==
                    open(self.background_png).read())


class TestBuildWebextDictionaryFromLegacy(AMOPaths, TestCase):
    def setUp(self):
        self.addon = addon_factory(
            target_locale='ar', type=amo.ADDON_DICT,
            version_kw={'version': '1.0'},
            file_kw={'is_webextension': False})
        self.xpi_copy_over(
            self.addon.current_version.all_files[0], 'dictionary-test.xpi')

    def check_xpi_file_contents(self, xpi_file_path, expected_version):
        with zipfile.ZipFile(xpi_file_path, 'r', zipfile.ZIP_DEFLATED) as xpi:
            # Check that manifest is present, contains proper version and
            # dictionaries properties.
            manifest = xpi.read('manifest.json')
            manifest_json = json.loads(manifest)
            assert (
                manifest_json['applications']['gecko']['id'] ==
                self.addon.guid)
            assert manifest_json['version'] == expected_version
            expected_dict_obj = {'ar': 'dictionaries/ar.dic'}
            assert manifest_json['dictionaries'] == expected_dict_obj

            # Check that we haven't included any useless files.
            expected_files = sorted([
                'dictionaries/',
                'dictionaries/ar.aff',
                'dictionaries/ar.dic',
                'dictionaries/license.txt',
                'manifest.json'
            ])
            assert sorted([x.filename for x in xpi.filelist]) == expected_files

    def test_basic(self):
        with tempfile.NamedTemporaryFile(suffix='.xpi') as destination:
            build_webext_dictionary_from_legacy(self.addon, destination)
            self.check_xpi_file_contents(destination, '1.0.1webext')

    def test_current_not_valid_raises(self):
        mod = 'olympia.files.utils.SafeZip.initialize_and_validate'
        with mock.patch(mod) as is_valid:
            is_valid.return_value = False
            with tempfile.NamedTemporaryFile(suffix='.xpi') as destination:
                with self.assertRaises(ValidationError):
                    build_webext_dictionary_from_legacy(
                        self.addon, destination)

    def test_addon_has_no_target_locale(self):
        self.addon.update(target_locale=None)
        with tempfile.NamedTemporaryFile(suffix='.xpi') as destination:
            build_webext_dictionary_from_legacy(self.addon, destination)
            self.check_xpi_file_contents(destination, '1.0.1webext')
        self.addon.reload()

    def test_invalid_dictionary_path_raises(self):
        self.xpi_copy_over(
            self.addon.current_version.all_files[0], 'extension.xpi')
        with tempfile.NamedTemporaryFile(suffix='.xpi') as destination:
            with self.assertRaises(ValidationError):
                build_webext_dictionary_from_legacy(self.addon, destination)

    def test_version_number_typefix(self):
        self.addon.current_version.update(version='1.1-typefix')
        with tempfile.NamedTemporaryFile(suffix='.xpi') as destination:
            build_webext_dictionary_from_legacy(self.addon, destination)
            self.check_xpi_file_contents(destination, '1.2webext')
