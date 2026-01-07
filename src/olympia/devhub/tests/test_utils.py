import json
import os.path
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.test.utils import override_settings

import pytest
from celery import group

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
)
from olympia.amo.tests.test_helpers import get_addon_file
from olympia.applications.models import AppVersion
from olympia.devhub import tasks, utils
from olympia.files.tasks import repack_fileupload
from olympia.files.tests.test_models import UploadMixin
from olympia.scanners.tasks import (
    call_webhooks_during_validation,
    run_customs,
    run_yara,
)
from olympia.versions.models import Version


class TestAddonsLinterListed(UploadMixin, TestCase):
    def setUp(self):
        # Create File objects for version 1.0 and 1.1.
        self.addon = addon_factory(
            guid='test-desktop@nowhere',
            slug='test-amo-addon',
            version_kw={'version': '1.0'},
            file_kw={'filename': 'webextension.xpi'},
        )
        self.version = self.addon.current_version
        self.file = self.version.file

        # Create a FileUpload object for an XPI containing version 1.1.
        self.file_upload = self.get_upload(
            abspath=self.file.file.path, with_validation=False
        )

        self.mock_chain = self.patch('olympia.devhub.utils.chain')

    def patch(self, thing):
        """Patch the given "thing", and revert the patch on test teardown."""
        patcher = mock.patch(thing)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_check_upload(self):
        """Check that the given new file upload is validated properly."""
        # Run validator.
        utils.Validator(self.file_upload)

        # Make sure we setup the correct validation task.
        self.mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(self.file_upload.pk),
            tasks.validate_upload.s(self.file_upload.pk),
            tasks.check_for_api_keys_in_file.s(self.file_upload.pk),
            tasks.check_data_collection_permissions.s(self.file_upload.pk),
            group([tasks.forward_linter_results.s(self.file_upload.pk)]),
            tasks.handle_upload_validation_result.s(self.file_upload.pk, False),
        )

    def test_check_file(self):
        """Check that the given file is validated properly."""
        # Mock tasks that we should not execute.
        repack_fileupload = self.patch('olympia.files.tasks.repack_fileupload')
        validate_upload = self.patch('olympia.devhub.tasks.validate_upload')

        # Run validator.
        utils.Validator(self.file)

        # We shouldn't be attempting to call the `validate_upload` tasks when
        # dealing with a file.
        assert not repack_fileupload.called
        assert not validate_upload.called

        # Make sure we setup the correct validation task.
        self.mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            tasks.validate_file.s(self.file.pk),
            tasks.handle_file_validation_result.s(self.file.pk),
        )

    def test_validate_non_theme_passing_theme_specific_arg(self):
        repack_fileupload = self.patch('olympia.files.tasks.repack_fileupload')
        validate_upload = self.patch('olympia.devhub.tasks.validate_upload')

        with self.assertRaises(utils.InvalidAddonType):
            utils.Validator(self.file_upload, theme_specific=True)
        assert not repack_fileupload.called
        assert not validate_upload.called


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
        validation = self.make_validation(['error', 'warning', 'notice', 'error'])
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
            'summary': {'errors': 0, 'notices': 0, 'warnings': 4},
            'metadata': {
                'manifestVersion': 2,
                'name': 'My Dogs New Tab',
                'type': 1,
                'version': '2.13.15',
                'architecture': 'extension',
                'emptyFiles': [],
                'jsLibs': {'lib/vendor/jquery.js': 'jquery.2.1.4.jquery.js'},
            },
            'errors': [],
            'notices': [],
            'warnings': [
                {
                    '_type': 'warning',
                    'code': 'MANIFEST_PERMISSIONS',
                    'message': '/permissions: Unknown permissions ...',
                    'description': 'See https://mzl.la/1R1n1t0 ...',
                    'file': 'manifest.json',
                },
                {
                    '_type': 'warning',
                    'code': 'MANIFEST_PERMISSIONS',
                    'message': '/permissions: Unknown permissions ...',
                    'description': 'See https://mzl.la/1R1n1t0 ....',
                    'file': 'manifest.json',
                },
                {
                    '_type': 'warning',
                    'code': 'MANIFEST_CSP',
                    'message': "'content_security_policy' is ...",
                    'description': 'A custom content_security_policy ...',
                },
                {
                    '_type': 'warning',
                    'code': 'NO_DOCUMENT_WRITE',
                    'message': 'Use of document.write strongly discouraged.',
                    'description': 'document.write will fail in...',
                    'column': 13,
                    'file': 'lib/vendor/knockout.js',
                    'line': 5449,
                },
            ],
        }

        fixed = utils.fix_addons_linter_output(original_output, amo.CHANNEL_LISTED)

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


@pytest.mark.django_db
@pytest.mark.parametrize(
    'zip_file',
    (
        'src/olympia/devhub/tests/addons/static_theme.zip',
        'src/olympia/devhub/tests/addons/static_theme_deprecated.zip',
    ),
)
def test_extract_theme_properties(zip_file):
    versions = {
        amo.DEFAULT_WEBEXT_MAX_VERSION,
        amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX,
    }
    for version in versions:
        AppVersion.objects.get_or_create(application=amo.FIREFOX.id, version=version)
        AppVersion.objects.get_or_create(application=amo.ANDROID.id, version=version)

    addon = addon_factory(
        type=amo.ADDON_STATICTHEME,
        file_kw={'filename': os.path.join(settings.ROOT, zip_file)},
    )
    result = utils.extract_theme_properties(addon, addon.current_version.channel)
    assert result == {
        'colors': {'frame': '#adb09f', 'tab_background_text': '#000'},
        'images': {'theme_frame': 'weta.png'},
    }

    addon.current_version.file.update(file='')
    result = utils.extract_theme_properties(addon, addon.current_version.channel)
    assert result == {}  # There's no file, but it be should safely handled.


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
    properties = utils.wizard_unsupported_properties(data, fields)
    assert properties == ['extrathing', 'extracolor', 'additionalBackground']


def test_process_validation_ending_tier_is_preserved():
    results = {
        'errors': 0,
        'success': True,
        'warnings': 0,
        'notices': 0,
        'message_tree': {},
        'messages': [],
        'ending_tier': 5,
        'metadata': {
            'version': '1.0',
            'name': 'gK0Bes Bot',
            'id': 'gkobes@gkobes',
        },
    }
    data = utils.process_validation(results)
    assert not data['errors']
    assert data['ending_tier'] == 5


class TestValidator(UploadMixin, TestCase):
    @mock.patch('olympia.devhub.utils.chain')
    def test_appends_final_task_for_file_uploads(self, mock_chain):
        final_task = mock.Mock()
        file_upload = self.get_upload('webextension.xpi', with_validation=False)

        utils.Validator(file_upload, final_task=final_task)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            tasks.check_data_collection_permissions.s(file_upload.pk),
            group([tasks.forward_linter_results.s(file_upload.pk)]),
            tasks.handle_upload_validation_result.s(file_upload.pk, False),
            final_task,
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_appends_final_task_for_files(self, mock_chain):
        final_task = mock.Mock()
        file = version_factory(addon=addon_factory()).file

        utils.Validator(file, final_task=final_task)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            tasks.validate_file.s(file.pk),
            tasks.handle_file_validation_result.s(file.pk),
            final_task,
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_adds_run_yara_when_enabled(self, mock_chain):
        self.create_switch('enable-yara', active=True)
        file_upload = self.get_upload('webextension.xpi', with_validation=False)

        utils.Validator(file_upload)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            tasks.check_data_collection_permissions.s(file_upload.pk),
            group(
                [
                    tasks.forward_linter_results.s(file_upload.pk),
                    run_yara.s(file_upload.pk),
                ]
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk, False),
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_does_not_add_run_yara_when_disabled(self, mock_chain):
        self.create_switch('enable-yara', active=False)
        file_upload = self.get_upload('webextension.xpi', with_validation=False)

        utils.Validator(file_upload)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            tasks.check_data_collection_permissions.s(file_upload.pk),
            group([tasks.forward_linter_results.s(file_upload.pk)]),
            tasks.handle_upload_validation_result.s(file_upload.pk, False),
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_adds_run_customs_when_enabled(self, mock_chain):
        self.create_switch('enable-customs', active=True)
        file_upload = self.get_upload('webextension.xpi', with_validation=False)

        utils.Validator(file_upload)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            tasks.check_data_collection_permissions.s(file_upload.pk),
            group(
                [
                    tasks.forward_linter_results.s(file_upload.pk),
                    run_customs.s(file_upload.pk),
                ]
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk, False),
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_does_not_add_run_customs_when_disabled(self, mock_chain):
        self.create_switch('enable-customs', active=False)
        file_upload = self.get_upload('webextension.xpi', with_validation=False)

        utils.Validator(file_upload)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            tasks.check_data_collection_permissions.s(file_upload.pk),
            group([tasks.forward_linter_results.s(file_upload.pk)]),
            tasks.handle_upload_validation_result.s(file_upload.pk, False),
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_adds_yara_and_customs(self, mock_chain):
        self.create_switch('enable-customs', active=True)
        self.create_switch('enable-yara', active=True)
        file_upload = self.get_upload('webextension.xpi', with_validation=False)

        utils.Validator(file_upload)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            tasks.check_data_collection_permissions.s(file_upload.pk),
            group(
                [
                    tasks.forward_linter_results.s(file_upload.pk),
                    run_yara.s(file_upload.pk),
                    run_customs.s(file_upload.pk),
                ]
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk, False),
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_adds_all_scanners(self, mock_chain):
        self.create_switch('enable-customs', active=True)
        self.create_switch('enable-yara', active=True)
        file_upload = self.get_upload('webextension.xpi', with_validation=False)

        utils.Validator(file_upload)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            tasks.check_data_collection_permissions.s(file_upload.pk),
            group(
                [
                    tasks.forward_linter_results.s(file_upload.pk),
                    run_yara.s(file_upload.pk),
                    run_customs.s(file_upload.pk),
                ]
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk, False),
        )

    def test_create_file_upload_tasks(self):
        self.create_switch('enable-customs', active=True)
        self.create_switch('enable-yara', active=True)
        file_upload = self.get_upload('webextension.xpi', with_validation=False)
        validator = utils.Validator(file_upload)

        tasks = validator.create_file_upload_tasks(
            upload_pk=file_upload.pk, is_mozilla_signed=False
        )

        assert isinstance(tasks, list)

        expected_tasks = [
            'olympia.devhub.tasks.create_initial_validation_results',
            'olympia.files.tasks.repack_fileupload',
            'olympia.devhub.tasks.validate_upload',
            'olympia.devhub.tasks.check_for_api_keys_in_file',
            'olympia.devhub.tasks.check_data_collection_permissions',
            'celery.group',
            'olympia.devhub.tasks.handle_upload_validation_result',
        ]
        assert len(tasks) == len(expected_tasks)
        assert expected_tasks == [task.name for task in tasks]

        scanners_group = tasks[5]

        expected_parallel_tasks = [
            'olympia.devhub.tasks.forward_linter_results',
            'olympia.scanners.tasks.run_yara',
            'olympia.scanners.tasks.run_customs',
        ]
        assert len(scanners_group.tasks) == len(expected_parallel_tasks)
        assert expected_parallel_tasks == [task.name for task in scanners_group.tasks]

    @mock.patch('olympia.devhub.utils.chain')
    def test_calls_webhooks_during_validation(self, mock_chain):
        self.create_switch('enable-scanner-webhooks', active=True)
        file_upload = self.get_upload('webextension.xpi', with_validation=False)

        utils.Validator(file_upload)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            tasks.check_data_collection_permissions.s(file_upload.pk),
            group(
                [
                    tasks.forward_linter_results.s(file_upload.pk),
                    call_webhooks_during_validation.s(file_upload.pk),
                ]
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk, False),
        )


class TestCreateVersionForUpload(UploadMixin, TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.mocks = {}
        for key in ['Version.from_upload', 'parse_addon', 'statsd.incr']:
            patcher = mock.patch('olympia.devhub.utils.%s' % key)
            self.mocks[key] = patcher.start()
            self.addCleanup(patcher.stop)
        self.user = user_factory()

    def test_statsd_logging_new_addon(self):
        empty_addon = Addon.objects.create()
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=empty_addon, version=None
        )
        utils.create_version_for_upload(
            addon=empty_addon,
            upload=upload,
            channel=amo.CHANNEL_LISTED,
            client_info=None,
        )
        assert self.mocks['parse_addon'].call_count == 1
        self.mocks['Version.from_upload'].assert_called()
        self.mocks['statsd.incr'].assert_any_call('signing.submission.addon.listed')

    def test_statsd_logging_new_version(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version=None
        )
        utils.create_version_for_upload(
            addon=self.addon,
            upload=upload,
            channel=amo.CHANNEL_LISTED,
            client_info=None,
        )
        assert self.mocks['parse_addon'].call_count == 1
        self.mocks['Version.from_upload'].assert_called()
        self.mocks['statsd.incr'].assert_any_call('signing.submission.version.listed')

    def test_file_passed_all_validations_not_most_recent(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0'
        )
        newer_upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0'
        )
        newer_upload.update(created=datetime.today() + timedelta(hours=1))

        # Check that the older file won't turn into a Version.
        utils.create_version_for_upload(
            addon=self.addon,
            upload=upload,
            channel=amo.CHANNEL_LISTED,
            client_info=None,
        )
        assert not self.mocks['Version.from_upload'].called

        # But the newer one will.
        utils.create_version_for_upload(
            addon=self.addon,
            upload=newer_upload,
            channel=amo.CHANNEL_LISTED,
            client_info=None,
        )
        self.mocks['Version.from_upload'].assert_called_with(
            newer_upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[amo.FIREFOX.id],
            parsed_data=self.mocks['parse_addon'].return_value,
            client_info=None,
        )

    def test_file_passed_all_validations_version_exists(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0'
        )
        Version.objects.create(addon=upload.addon, version=upload.version)

        # Check that the older file won't turn into a Version.
        utils.create_version_for_upload(
            addon=self.addon,
            upload=upload,
            channel=amo.CHANNEL_LISTED,
            client_info=None,
        )
        assert not self.mocks['Version.from_upload'].called

    def test_file_passed_all_validations_most_recent_failed(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0'
        )
        newer_upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0'
        )
        newer_upload.update(
            created=datetime.today() + timedelta(hours=1),
            valid=False,
            validation=json.dumps({'errors': 5}),
        )

        utils.create_version_for_upload(
            addon=self.addon,
            upload=upload,
            channel=amo.CHANNEL_LISTED,
            client_info=None,
        )
        assert not self.mocks['Version.from_upload'].called

    def test_file_passed_all_validations_most_recent(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0'
        )
        newer_upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='0.5'
        )
        newer_upload.update(created=datetime.today() + timedelta(hours=1))

        # The Version is created because the newer upload is for a different
        # version_string.
        utils.create_version_for_upload(
            addon=self.addon,
            upload=upload,
            channel=amo.CHANNEL_LISTED,
            client_info=None,
        )
        self.mocks['parse_addon'].assert_called_with(
            upload, addon=self.addon, user=self.user
        )
        self.mocks['Version.from_upload'].assert_called_with(
            upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[amo.FIREFOX.id],
            parsed_data=self.mocks['parse_addon'].return_value,
            client_info=None,
        )

    def test_file_passed_all_validations_beta_string(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0beta1'
        )
        utils.create_version_for_upload(
            addon=self.addon,
            upload=upload,
            channel=amo.CHANNEL_LISTED,
            client_info=None,
        )
        self.mocks['parse_addon'].assert_called_with(
            upload, addon=self.addon, user=self.user
        )
        self.mocks['Version.from_upload'].assert_called_with(
            upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[amo.FIREFOX.id],
            parsed_data=self.mocks['parse_addon'].return_value,
            client_info=None,
        )

    def test_file_passed_all_validations_no_version(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version=None
        )
        utils.create_version_for_upload(
            addon=self.addon,
            upload=upload,
            channel=amo.CHANNEL_LISTED,
            client_info=None,
        )
        self.mocks['parse_addon'].assert_called_with(
            upload, addon=self.addon, user=self.user
        )
        self.mocks['Version.from_upload'].assert_called_with(
            upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[amo.FIREFOX.id],
            parsed_data=self.mocks['parse_addon'].return_value,
            client_info=None,
        )
