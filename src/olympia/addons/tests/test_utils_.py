# -*- coding: utf-8 -*-
import json
from unittest import mock
import pytest
import tempfile
import zipfile

from django.conf import settings
from django.forms import ValidationError
from django.utils.encoding import force_text

from olympia import amo
from olympia.addons.utils import (
    build_webext_dictionary_from_legacy,
    get_addon_recommendations, get_addon_recommendations_invalid,
    is_outcome_recommended,
    TAAR_LITE_FALLBACK_REASON_EMPTY, TAAR_LITE_FALLBACK_REASON_TIMEOUT,
    TAAR_LITE_FALLBACKS, TAAR_LITE_OUTCOME_CURATED,
    TAAR_LITE_OUTCOME_REAL_FAIL, TAAR_LITE_OUTCOME_REAL_SUCCESS,
    TAAR_LITE_FALLBACK_REASON_INVALID,
    verify_mozilla_trademark)
from olympia.amo.tests import AMOPaths, TestCase, addon_factory, user_factory


@pytest.mark.django_db
@pytest.mark.parametrize('name, allowed, email', (
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
            'Add-on names cannot contain the Mozilla or Firefox '
            'trademarks.'
        )
    else:
        verify_mozilla_trademark(name, user)


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
        self.recommendation_server_mock.assert_called_with(
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, 'a@b', {})

    def test_recommended_no_results(self):
        self.recommendation_server_mock.return_value = []
        recommendations, outcome, reason = get_addon_recommendations(
            'a@b', True)
        assert recommendations == TAAR_LITE_FALLBACKS
        assert outcome == TAAR_LITE_OUTCOME_REAL_FAIL
        assert reason is TAAR_LITE_FALLBACK_REASON_EMPTY
        self.recommendation_server_mock.assert_called_with(
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, 'a@b', {})

    def test_recommended_timeout(self):
        self.recommendation_server_mock.return_value = None
        recommendations, outcome, reason = get_addon_recommendations(
            'a@b', True)
        assert recommendations == TAAR_LITE_FALLBACKS
        assert outcome == TAAR_LITE_OUTCOME_REAL_FAIL
        assert reason is TAAR_LITE_FALLBACK_REASON_TIMEOUT
        self.recommendation_server_mock.assert_called_with(
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, 'a@b', {})

    def test_not_recommended(self):
        recommendations, outcome, reason = get_addon_recommendations(
            'a@b', False)
        assert not self.recommendation_server_mock.called
        assert recommendations == TAAR_LITE_FALLBACKS
        assert outcome == TAAR_LITE_OUTCOME_CURATED
        assert reason is None

    def test_invalid_fallback(self):
        recommendations, outcome, reason = get_addon_recommendations_invalid()
        assert not self.recommendation_server_mock.called
        assert recommendations == TAAR_LITE_FALLBACKS
        assert outcome == TAAR_LITE_OUTCOME_REAL_FAIL
        assert reason == TAAR_LITE_FALLBACK_REASON_INVALID

    def test_is_outcome_recommended(self):
        assert is_outcome_recommended(TAAR_LITE_OUTCOME_REAL_SUCCESS)
        assert not is_outcome_recommended(TAAR_LITE_OUTCOME_REAL_FAIL)
        assert not is_outcome_recommended(TAAR_LITE_OUTCOME_CURATED)
        assert not self.recommendation_server_mock.called


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
            manifest = force_text(xpi.read('manifest.json'))
            manifest_json = json.loads(manifest)
            assert (
                manifest_json['browser_specific_settings']['gecko']['id'] ==
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
