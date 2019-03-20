# -*- coding: utf-8 -*-
import os.path

from django.conf import settings
from django.forms import ValidationError
from django.test.utils import override_settings

import mock
import pytest
from waffle.testutils import override_switch

from celery.result import AsyncResult
from six import text_type

from olympia import amo
from olympia.amo.storage_utils import copy_stored_file
from olympia.amo.tests import (
    addon_factory, TestCase, user_factory, version_factory)
from olympia.applications.models import AppVersion
from olympia.devhub import tasks, utils
from olympia.files.tests.test_models import UploadTest
from olympia.lib.akismet.models import AkismetReport


class TestAddonsLinterListed(UploadTest, TestCase):

    def setUp(self):
        # Create File objects for version 1.0 and 1.1.
        self.addon = addon_factory(
            guid='test-desktop@nowhere', slug='test-amo-addon',
            version_kw={'version': '1.0'},
            file_kw={'filename': 'webextension.xpi'})
        self.version = self.addon.current_version
        self.file = self.version.current_file

        # Create a FileUpload object for an XPI containing version 1.1.
        self.file_upload = self.get_upload(
            abspath=self.file.current_file_path, with_validation=False)

        # Patch validation tasks that we expect the validator to call.
        self.save_file = self.patch(
            'olympia.devhub.tasks.handle_file_validation_result').s
        self.save_upload = self.patch(
            'olympia.devhub.tasks.handle_upload_validation_result').s

        self.validate_file = self.patch(
            'olympia.devhub.tasks.validate_file').si
        self.validate_upload = self.patch(
            'olympia.devhub.tasks.validate_upload').si

    def patch(self, thing):
        """Patch the given "thing", and revert the patch on test teardown."""
        patcher = mock.patch(thing)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def check_upload(self, file_upload, listed=True):
        """Check that the given new file upload is validated properly."""
        # Run validator.
        utils.Validator(file_upload, listed=listed)

        # We shouldn't be attempting to call validate_file task when dealing
        # with an upload.
        assert not self.validate_file.called

        channel = (amo.RELEASE_CHANNEL_LISTED if listed
                   else amo.RELEASE_CHANNEL_UNLISTED)

        # Make sure we run the correct validation task for the upload and we
        # set up an error handler.
        self.validate_upload.assert_called_once_with(
            file_upload.pk, channel=channel)
        assert self.validate_upload.return_value.on_error.called

        # Make sure we run the correct save validation task.
        self.save_upload.assert_called_once_with(
            file_upload.pk, channel, False)

    def check_file(self, file_):
        """Check that the given file is validated properly."""
        # Run validator.
        utils.Validator(file_)

        # We shouldn't be attempting to call validate_upload task when
        # dealing with a file.
        assert not self.validate_upload.called

        # Make sure we run the correct validation task and we set up an error
        # handler.
        self.validate_file.assert_called_once_with(file_.pk)
        assert self.validate_file.return_value.on_error.called

        # Make sure we run the correct save validation task.
        self.save_file.assert_called_once_with(
            file_.pk, file_.version.channel, False)

    @mock.patch.object(utils.Validator, 'get_task')
    def test_run_once_per_file(self, get_task_mock):
        """Tests that only a single validation task is run for a given file."""
        get_task_mock.return_value.delay.return_value = mock.Mock(task_id='42')

        assert isinstance(tasks.validate(self.file), mock.Mock)
        assert get_task_mock.return_value.delay.call_count == 1

        assert isinstance(tasks.validate(self.file), AsyncResult)
        assert get_task_mock.return_value.delay.call_count == 1

        new_version = version_factory(addon=self.addon, version='0.0.2')
        assert isinstance(tasks.validate(new_version.current_file), mock.Mock)
        assert get_task_mock.return_value.delay.call_count == 2

    @mock.patch.object(utils.Validator, 'get_task')
    def test_run_once_file_upload(self, get_task_mock):
        """Tests that only a single validation task is run for a given file
        upload."""
        get_task_mock.return_value.delay.return_value = mock.Mock(task_id='42')

        assert isinstance(
            tasks.validate(self.file_upload, listed=True), mock.Mock)
        assert get_task_mock.return_value.delay.call_count == 1

        assert isinstance(
            tasks.validate(self.file_upload, listed=True), AsyncResult)
        assert get_task_mock.return_value.delay.call_count == 1

    def test_cache_key(self):
        """Tests that the correct cache key is generated for a given object."""

        assert (utils.Validator(self.file).cache_key ==
                'validation-task:files.File:{0}:None'.format(self.file.pk))

        assert (utils.Validator(self.file_upload, listed=False).cache_key ==
                'validation-task:files.FileUpload:{0}:False'.format(
                    self.file_upload.pk))

    @mock.patch('olympia.devhub.utils.parse_addon')
    def test_search_plugin(self, parse_addon):
        """Test that search plugins are handled correctly (new upload)."""
        parse_addon.return_value = {
            'guid': None,
            'version': '20140103',
        }

        addon = addon_factory(type=amo.ADDON_SEARCH,
                              version_kw={'version': '20140101'})
        assert addon.guid is None
        self.check_upload(self.file_upload)

    @mock.patch('olympia.devhub.utils.parse_addon')
    def test_search_plugin_file(self, parse_addon):
        """Test that search plugins are handled correctly (existing file)."""
        parse_addon.return_value = {
            'guid': None,
            'version': '20140103',
        }

        addon = addon_factory(type=amo.ADDON_SEARCH,
                              version_kw={'version': '20140101'})
        version = version_factory(addon=addon, version='20140102')
        self.check_file(version.files.get())


class TestLimitAddonsLinterResults(TestCase):
    """Test that higher priority messages are truncated last."""

    def make_validation(self, types):
        """Take a list of error types and make a
        validation results dict."""
        validation = {
            'messages': [],
            'errors': 0,
            'warnings': 0,
            'notices': 0,
        }
        severities = ['low', 'medium', 'high']
        for type_ in types:
            if type_ in severities:
                type_ = 'warning'
            validation[type_ + 's'] += 1
            validation['messages'].append({'type': type_})
        return validation

    @override_settings(VALIDATOR_MESSAGE_LIMIT=2)
    def test_errors_are_first(self):
        validation = self.make_validation(
            ['error', 'warning', 'notice', 'error'])
        utils.limit_validation_results(validation)
        limited = validation['messages']
        assert len(limited) == 3
        assert '2 messages were truncated' in limited[0]['message']
        assert limited[1]['type'] == 'error'
        assert limited[2]['type'] == 'error'


class TestFixAddonsLinterOutput(TestCase):

    def test_fix_output(self):
        original_output = {
            'count': 4,
            'summary': {
                'errors': 0,
                'notices': 0,
                'warnings': 4
            },
            'metadata': {
                'manifestVersion': 2,
                'name': 'My Dogs New Tab',
                'type': 1,
                'version': '2.13.15',
                'architecture': 'extension',
                'emptyFiles': [],
                'jsLibs': {
                    'lib/vendor/jquery.js': 'jquery.2.1.4.jquery.js'
                }
            },
            'errors': [],
            'notices': [],
            'warnings': [
                {
                    '_type': 'warning',
                    'code': 'MANIFEST_PERMISSIONS',
                    'message': '/permissions: Unknown permissions ...',
                    'description': 'See https://mzl.la/1R1n1t0 ...',
                    'file': 'manifest.json'
                },
                {
                    '_type': 'warning',
                    'code': 'MANIFEST_PERMISSIONS',
                    'message': '/permissions: Unknown permissions ...',
                    'description': 'See https://mzl.la/1R1n1t0 ....',
                    'file': 'manifest.json'
                },
                {
                    '_type': 'warning',
                    'code': 'MANIFEST_CSP',
                    'message': '\'content_security_policy\' is ...',
                    'description': 'A custom content_security_policy ...'
                },
                {
                    '_type': 'warning',
                    'code': 'NO_DOCUMENT_WRITE',
                    'message': 'Use of document.write strongly discouraged.',
                    'description': 'document.write will fail in...',
                    'column': 13,
                    'file': 'lib/vendor/knockout.js',
                    'line': 5449
                }
            ]
        }

        fixed = utils.fix_addons_linter_output(
            original_output, amo.RELEASE_CHANNEL_LISTED)

        assert fixed['success']
        assert fixed['warnings'] == 4
        assert 'uid' in fixed['messages'][0]
        assert 'id' in fixed['messages'][0]
        assert 'type' in fixed['messages'][0]
        assert fixed['messages'][0]['tier'] == 1
        assert fixed['compatibility_summary'] == {
            'warnings': 0,
            'errors': 0,
            'notices': 0,
        }
        assert fixed['ending_tier'] == 5
        assert fixed['metadata']['listed'] is True
        assert fixed['metadata']['identified_files'] == {
            'lib/vendor/jquery.js': {'path': 'jquery.2.1.4.jquery.js'}
        }
        # Make sure original metadata was preserved.
        for key, value in original_output['metadata'].items():
            assert fixed['metadata'][key] == value


@override_switch('akismet-spam-check', active=True)
class TestGetAddonAkismetReports(UploadTest, TestCase):
    def setUp(self):
        super(TestGetAddonAkismetReports, self).setUp()

        patcher = mock.patch.object(
            AkismetReport, 'create_for_addon')
        self.addCleanup(patcher.stop)
        self.create_for_addon_mock = patcher.start()
        self.parse_addon_mock = self.patch('olympia.devhub.utils.parse_addon')

    @override_switch('akismet-spam-check', active=False)
    def test_waffle_off(self):
        reports = utils.get_addon_akismet_reports(
            None, '', '')
        assert reports == []
        self.create_for_addon_mock.assert_not_called()

    def test_upload(self):
        user = user_factory()
        upload = self.get_upload('webextension.xpi')
        self.parse_addon_mock.return_value = {'description': u'fóó'}
        user_agent = 'Mr User/Agent'
        referrer = 'http://foo.baa/'
        reports = utils.get_addon_akismet_reports(
            user, user_agent, referrer, upload=upload)
        assert len(reports) == 1
        self.create_for_addon_mock.assert_called_with(
            upload=upload, addon=None, user=user, property_name='description',
            property_value=u'fóó', user_agent=user_agent, referrer=referrer)
        self.create_for_addon_mock.assert_called_once()

    def test_upload_with_addon(self):
        # Give addon some existing metadata.
        addon = addon_factory()
        user = user_factory()
        upload = self.get_upload('webextension.xpi', addon=addon)
        # summary is parsed but it's in existing_data - i.e. should have
        # been spam checked previous it so will be ignored.
        self.parse_addon_mock.return_value = {
            'name': u'fóó', 'summary': u'summáry'}
        user_agent = 'Mr User/Agent'
        referrer = 'http://foo.baa/'
        reports = utils.get_addon_akismet_reports(
            user, user_agent, referrer, upload=upload,
            existing_data=[u'summáry'])
        # only one, no summary because it's in existing data
        assert len(reports) == 1
        self.create_for_addon_mock.assert_called_with(
            upload=upload, addon=addon, user=user, property_name='name',
            property_value=u'fóó', user_agent=user_agent, referrer=referrer)
        self.create_for_addon_mock.assert_called_once()

    def test_upload_locales(self):
        addon = addon_factory(summary=u'¡Ochó!', default_locale='es-AR')
        user = user_factory()
        upload = self.get_upload('webextension.xpi', addon=addon)
        existing_data = utils.fetch_existing_translations_from_addon(
            addon, ('summary', 'name', 'description'))
        # check fetch_existing_translations_from_addon worked okay
        assert existing_data == {text_type(addon.name), u'¡Ochó!'}
        self.parse_addon_mock.return_value = {
            'description': {
                'en-US': u'fóó',
                'fr': u'lé foo',
                'de': '',  # should be ignored because empty
                'es-ES': u'¡Ochó!'  # ignored because in existing_data
            },
            'name': u'just one name',
            'summary': None,  # should also be ignored because None
        }
        user_agent = 'Mr User/Agent'
        referrer = 'http://foo.baa/'
        reports = utils.get_addon_akismet_reports(
            user, user_agent, referrer, upload=upload,
            existing_data=existing_data)
        assert len(reports) == 3
        assert self.create_for_addon_mock.call_count == 3
        calls = [
            mock.call(
                upload=upload, addon=addon, user=user,
                property_name='name', property_value=u'just one name',
                user_agent=user_agent, referrer=referrer),
            mock.call(
                upload=upload, addon=addon, user=user,
                property_name='description', property_value=u'fóó',
                user_agent=user_agent, referrer=referrer),
            mock.call(
                upload=upload, addon=addon, user=user,
                property_name='description', property_value=u'lé foo',
                user_agent=user_agent, referrer=referrer)]
        self.create_for_addon_mock.assert_has_calls(calls, any_order=True)

    def test_addon_update(self):
        addon = addon_factory(summary=u'¡Ochó!', default_locale='es-AR')
        user = user_factory()
        existing_data = utils.fetch_existing_translations_from_addon(
            addon, ('summary', 'name', 'description'))
        # check fetch_existing_translations_from_addon worked okay
        assert existing_data == {text_type(addon.name), u'¡Ochó!'}
        cleaned_data = {
            'description': {
                'en-US': u'fóó',
                'fr': u'lé foo',
                'de': '',  # should be ignored because empty
                'es-ES': u'¡Ochó!'  # ignored because in exist_data
            },
            'name': {
                'en-GB': u'just one name',
                'fr': None,
            },
        }
        user_agent = 'Mr User/Agent'
        referrer = 'http://foo.baa/'
        reports = utils.get_addon_akismet_reports(
            user, user_agent, referrer, addon=addon, data=cleaned_data,
            existing_data=existing_data)
        assert len(reports) == 3
        assert self.create_for_addon_mock.call_count == 3
        calls = [
            mock.call(
                upload=None, addon=addon, user=user,
                property_name='name', property_value=u'just one name',
                user_agent=user_agent, referrer=referrer),
            mock.call(
                upload=None, addon=addon, user=user,
                property_name='description', property_value=u'fóó',
                user_agent=user_agent, referrer=referrer),
            mock.call(
                upload=None, addon=addon, user=user,
                property_name='description', property_value=u'lé foo',
                user_agent=user_agent, referrer=referrer)]
        self.create_for_addon_mock.assert_has_calls(calls, any_order=True)

    def test_broken_upload(self):
        user = user_factory()
        upload = self.get_upload('webextension.xpi')
        self.parse_addon_mock.side_effect = ValidationError('foo')
        user_agent = 'Mr User/Agent'
        referrer = 'http://foo.baa/'
        reports = utils.get_addon_akismet_reports(
            user, user_agent, referrer, upload=upload)
        assert reports == []
        self.create_for_addon_mock.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    'zip_file', (
        'src/olympia/devhub/tests/addons/static_theme.zip',
        'src/olympia/devhub/tests/addons/static_theme_deprecated.zip',
    )
)
def test_extract_theme_properties(zip_file):
    versions = {
        amo.DEFAULT_WEBEXT_MAX_VERSION,
        amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX,
        amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID,
    }
    for version in versions:
        AppVersion.objects.create(application=amo.FIREFOX.id, version=version)
        AppVersion.objects.create(application=amo.ANDROID.id, version=version)

    addon = addon_factory(type=amo.ADDON_STATICTHEME)
    result = utils.extract_theme_properties(
        addon, addon.current_version.channel)
    assert result == {}  # There's no file, but it be should safely handled.

    # Add the zip in the right place
    zip_file = os.path.join(settings.ROOT, zip_file)
    copy_stored_file(zip_file, addon.current_version.all_files[0].file_path)
    result = utils.extract_theme_properties(
        addon, addon.current_version.channel)
    assert result == {
        "colors": {
            "frame": "#adb09f",
            "tab_background_text": "#000"
        },
        "images": {
            "theme_frame": "weta.png"
        }
    }


@pytest.mark.django_db
def test_wizard_unsupported_properties():
    data = {
        'colors': {
            'foo': '#111111',
            'baa': '#222222',
            'extracolor': 'rgb(1,2,3,0)',
        },
        'images': {
            'theme_frame': 'png.png',
            'additionalBackground': 'somethingelse.png',
        },
        'extrathing': {
            'doesnt': 'matter',
        },
    }
    fields = ['foo', 'baa']
    properties = utils.wizard_unsupported_properties(
        data, fields)
    assert properties == ['extrathing', 'extracolor', 'additionalBackground']
