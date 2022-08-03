import json
import os.path
from copy import deepcopy
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.test.utils import override_settings

import pytest

from celery import chord
from celery.result import AsyncResult
from waffle.testutils import override_switch

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import (
    addon_factory,
    TestCase,
    user_factory,
    version_factory,
)
from olympia.amo.tests.test_helpers import get_addon_file
from olympia.applications.models import AppVersion
from olympia.devhub import tasks, utils
from olympia.files.tasks import repack_fileupload
from olympia.files.tests.test_models import UploadMixin
from olympia.scanners.tasks import run_customs, run_yara, call_mad_api
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
            abspath=self.file.file_path, with_validation=False
        )

        self.mock_chain = self.patch('olympia.devhub.utils.chain')

    def patch(self, thing):
        """Patch the given "thing", and revert the patch on test teardown."""
        patcher = mock.patch(thing)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def check_upload(self, file_upload, listed=True):
        """Check that the given new file upload is validated properly."""
        # Run validator.
        utils.Validator(file_upload, listed=listed)

        channel = amo.CHANNEL_LISTED if listed else amo.CHANNEL_UNLISTED

        # Make sure we setup the correct validation task.
        self.mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk, channel),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            chord(
                [tasks.forward_linter_results.s(file_upload.pk)],
                call_mad_api.s(file_upload.pk),
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk, channel, False),
        )

    def check_file(self, file_):
        """Check that the given file is validated properly."""
        # Mock tasks that we should not execute.
        repack_fileupload = self.patch('olympia.files.tasks.repack_fileupload')
        validate_upload = self.patch('olympia.devhub.tasks.validate_upload')

        # Run validator.
        utils.Validator(file_)

        # We shouldn't be attempting to call the `validate_upload` tasks when
        # dealing with a file.
        assert not repack_fileupload.called
        assert not validate_upload.called

        # Make sure we setup the correct validation task.
        self.mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            tasks.validate_file.s(file_.pk),
            tasks.handle_file_validation_result.s(file_.pk),
        )

    @mock.patch.object(utils.Validator, 'get_task')
    def test_run_once_per_file(self, get_task_mock):
        """Tests that only a single validation task is run for a given file."""
        get_task_mock.return_value.delay.return_value = mock.Mock(task_id='42')

        assert isinstance(tasks.validate(self.file), mock.Mock)
        assert get_task_mock.return_value.delay.call_count == 1

        assert isinstance(tasks.validate(self.file), AsyncResult)
        assert get_task_mock.return_value.delay.call_count == 1

        new_version = version_factory(addon=self.addon, version='0.0.2')
        assert isinstance(tasks.validate(new_version.file), mock.Mock)
        assert get_task_mock.return_value.delay.call_count == 2

    @mock.patch.object(utils.Validator, 'get_task')
    def test_run_once_file_upload(self, get_task_mock):
        """Tests that only a single validation task is run for a given file
        upload."""
        get_task_mock.return_value.delay.return_value = mock.Mock(task_id='42')

        assert isinstance(tasks.validate(self.file_upload, listed=True), mock.Mock)
        assert get_task_mock.return_value.delay.call_count == 1

        assert isinstance(tasks.validate(self.file_upload, listed=True), AsyncResult)
        assert get_task_mock.return_value.delay.call_count == 1

    def test_cache_key(self):
        """Tests that the correct cache key is generated for a given object."""

        assert (
            utils.Validator(self.file).cache_key
            == f'validation-task:files.File:{self.file.pk}:None'
        )

        assert utils.Validator(
            self.file_upload, listed=False
        ).cache_key == 'validation-task:files.FileUpload:{}:False'.format(
            self.file_upload.pk
        )


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

        fixed = utils.fix_addons_linter_output(
            original_output, amo.CHANNEL_LISTED
        )

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
        amo.DEFAULT_STATIC_THEME_MIN_VERSION_ANDROID,
    }
    for version in versions:
        AppVersion.objects.create(application=amo.FIREFOX.id, version=version)
        AppVersion.objects.create(application=amo.ANDROID.id, version=version)

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
        channel = amo.CHANNEL_LISTED

        utils.Validator(file_upload, listed=True, final_task=final_task)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk, channel),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            chord(
                [tasks.forward_linter_results.s(file_upload.pk)],
                call_mad_api.s(file_upload.pk),
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk, channel, False),
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
        channel = amo.CHANNEL_LISTED

        utils.Validator(file_upload, listed=True)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk, channel),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            chord(
                [
                    tasks.forward_linter_results.s(file_upload.pk),
                    run_yara.s(file_upload.pk),
                ],
                call_mad_api.s(file_upload.pk),
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk, channel, False),
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_does_not_add_run_yara_when_disabled(self, mock_chain):
        self.create_switch('enable-yara', active=False)
        file_upload = self.get_upload('webextension.xpi', with_validation=False)
        channel = amo.CHANNEL_LISTED

        utils.Validator(file_upload, listed=True)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk, channel),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            chord(
                [tasks.forward_linter_results.s(file_upload.pk)],
                call_mad_api.s(file_upload.pk),
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk, channel, False),
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_adds_run_customs_when_enabled(self, mock_chain):
        self.create_switch('enable-customs', active=True)
        file_upload = self.get_upload('webextension.xpi', with_validation=False)
        channel = amo.CHANNEL_LISTED

        utils.Validator(file_upload, listed=True)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk, channel),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            chord(
                [
                    tasks.forward_linter_results.s(file_upload.pk),
                    run_customs.s(file_upload.pk),
                ],
                call_mad_api.s(file_upload.pk),
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk, channel, False),
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_does_not_add_run_customs_when_disabled(self, mock_chain):
        self.create_switch('enable-customs', active=False)
        file_upload = self.get_upload('webextension.xpi', with_validation=False)
        channel = amo.CHANNEL_LISTED

        utils.Validator(file_upload, listed=True)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk, channel),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            chord(
                [tasks.forward_linter_results.s(file_upload.pk)],
                call_mad_api.s(file_upload.pk),
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk, channel, False),
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_adds_yara_and_customs(self, mock_chain):
        self.create_switch('enable-customs', active=True)
        self.create_switch('enable-yara', active=True)
        file_upload = self.get_upload('webextension.xpi', with_validation=False)
        channel = amo.CHANNEL_LISTED

        utils.Validator(file_upload, listed=True)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk, channel),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            chord(
                [
                    tasks.forward_linter_results.s(file_upload.pk),
                    run_yara.s(file_upload.pk),
                    run_customs.s(file_upload.pk),
                ],
                call_mad_api.s(file_upload.pk),
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk, channel, False),
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_adds_all_scanners(self, mock_chain):
        self.create_switch('enable-customs', active=True)
        self.create_switch('enable-yara', active=True)
        file_upload = self.get_upload('webextension.xpi', with_validation=False)
        channel = amo.CHANNEL_LISTED

        utils.Validator(file_upload, listed=True)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk, channel),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            chord(
                [
                    tasks.forward_linter_results.s(file_upload.pk),
                    run_yara.s(file_upload.pk),
                    run_customs.s(file_upload.pk),
                ],
                call_mad_api.s(file_upload.pk),
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk, channel, False),
        )

    def test_create_file_upload_tasks(self):
        self.create_switch('enable-customs', active=True)
        self.create_switch('enable-yara', active=True)
        file_upload = self.get_upload('webextension.xpi', with_validation=False)
        channel = amo.CHANNEL_LISTED
        validator = utils.Validator(file_upload, listed=True)

        tasks = validator.create_file_upload_tasks(
            upload_pk=file_upload.pk, channel=channel, is_mozilla_signed=False
        )

        assert isinstance(tasks, list)

        expected_tasks = [
            'olympia.devhub.tasks.create_initial_validation_results',
            'olympia.files.tasks.repack_fileupload',
            'olympia.devhub.tasks.validate_upload',
            'olympia.devhub.tasks.check_for_api_keys_in_file',
            'celery.chord',
            'olympia.devhub.tasks.handle_upload_validation_result',
        ]
        assert len(tasks) == len(expected_tasks)
        assert expected_tasks == [task.name for task in tasks]

        scanners_chord = tasks[4]

        expected_parallel_tasks = [
            'olympia.devhub.tasks.forward_linter_results',
            'olympia.scanners.tasks.run_yara',
            'olympia.scanners.tasks.run_customs',
        ]
        assert len(scanners_chord.tasks) == len(expected_parallel_tasks)
        assert expected_parallel_tasks == [task.name for task in scanners_chord.tasks]
        # Callback
        assert scanners_chord.body.name == 'olympia.scanners.tasks.call_mad_api'


def test_add_manifest_version_error():
    validation = deepcopy(amo.VALIDATOR_SKELETON_EXCEPTION_WEBEXT)
    len(validation['messages']) == 1

    # Add the error message when the manifest_version is 3.
    # The manifest_version error isn't in VALIDATOR_SKELETON_EXCEPTION_WEBEXT.
    validation['metadata']['manifestVersion'] = 3
    utils.add_manifest_version_error(validation)
    assert 'https://blog.mozilla.org/addons/2021/05/27/manifest-v3-update/' in (
        validation['messages'][0]['message']
    )
    assert len(validation['messages']) == 2  # we added it

    # When the linter error is already there, replace it
    validation['messages'] = [
        {
            'message': '"/manifest_version" should be &lt;= 2',
            'description': ['Your JSON file could not be parsed.'],
            'dataPath': '/manifest_version',
            'type': 'error',
            'tier': 1,
        }
    ]
    utils.add_manifest_version_error(validation)
    assert 'https://blog.mozilla.org/addons/2021/05/27/manifest-v3-update/' in (
        validation['messages'][0]['message']
    )
    assert len(validation['messages']) == 1  # we replaced it

    # Not if the mv3 waffle switch is enabled though
    with override_switch('enable-mv3-submissions', active=True):
        validation['messages'] = []
        utils.add_manifest_version_error(validation)
        assert validation['messages'] == []

    # Or if the manifest_version != 3
    validation['metadata']['manifestVersion'] = 2
    utils.add_manifest_version_error(validation)
    assert validation['messages'] == []


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
        parsed_data = mock.Mock()
        utils.create_version_for_upload(
            empty_addon, upload, amo.CHANNEL_LISTED, parsed_data=parsed_data
        )
        assert self.mocks['parse_addon'].call_count == 0
        self.mocks['Version.from_upload'].assert_called()
        self.mocks['statsd.incr'].assert_any_call('signing.submission.addon.listed')

    def test_statsd_logging_new_version(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version=None
        )
        parsed_data = mock.Mock()
        utils.create_version_for_upload(
            self.addon, upload, amo.CHANNEL_LISTED, parsed_data=parsed_data
        )
        assert self.mocks['parse_addon'].call_count == 0
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
        utils.create_version_for_upload(self.addon, upload, amo.CHANNEL_LISTED)
        assert not self.mocks['Version.from_upload'].called

        # But the newer one will.
        utils.create_version_for_upload(
            self.addon, newer_upload, amo.CHANNEL_LISTED
        )
        self.mocks['Version.from_upload'].assert_called_with(
            newer_upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[amo.FIREFOX.id, amo.ANDROID.id],
            parsed_data=self.mocks['parse_addon'].return_value,
        )

    def test_file_passed_all_validations_version_exists(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0'
        )
        Version.objects.create(addon=upload.addon, version=upload.version)

        # Check that the older file won't turn into a Version.
        utils.create_version_for_upload(self.addon, upload, amo.CHANNEL_LISTED)
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

        utils.create_version_for_upload(self.addon, upload, amo.CHANNEL_LISTED)
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
        utils.create_version_for_upload(self.addon, upload, amo.CHANNEL_LISTED)
        self.mocks['parse_addon'].assert_called_with(upload, self.addon, user=self.user)
        self.mocks['Version.from_upload'].assert_called_with(
            upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[amo.FIREFOX.id, amo.ANDROID.id],
            parsed_data=self.mocks['parse_addon'].return_value,
        )

    def test_file_passed_all_validations_beta_string(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version='1.0beta1'
        )
        utils.create_version_for_upload(self.addon, upload, amo.CHANNEL_LISTED)
        self.mocks['parse_addon'].assert_called_with(upload, self.addon, user=self.user)
        self.mocks['Version.from_upload'].assert_called_with(
            upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[amo.FIREFOX.id, amo.ANDROID.id],
            parsed_data=self.mocks['parse_addon'].return_value,
        )

    def test_file_passed_all_validations_no_version(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version=None
        )
        utils.create_version_for_upload(self.addon, upload, amo.CHANNEL_LISTED)
        self.mocks['parse_addon'].assert_called_with(upload, self.addon, user=self.user)
        self.mocks['Version.from_upload'].assert_called_with(
            upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[amo.FIREFOX.id, amo.ANDROID.id],
            parsed_data=self.mocks['parse_addon'].return_value,
        )

    def test_pass_parsed_data(self):
        file_ = get_addon_file('valid_webextension.xpi')
        upload = self.get_upload(
            abspath=file_, user=self.user, addon=self.addon, version=None
        )
        parsed_data = mock.Mock()
        utils.create_version_for_upload(
            self.addon, upload, amo.CHANNEL_LISTED, parsed_data=parsed_data
        )
        assert self.mocks['parse_addon'].call_count == 0
        self.mocks['Version.from_upload'].assert_called_with(
            upload,
            self.addon,
            amo.CHANNEL_LISTED,
            selected_apps=[amo.FIREFOX.id, amo.ANDROID.id],
            parsed_data=parsed_data,
        )
