# -*- coding: utf-8 -*-
import os.path

from django.conf import settings
from django.test.client import RequestFactory
from django.test.utils import override_settings

from unittest import mock
import pytest

from celery import chord
from celery.result import AsyncResult

from olympia import amo
from olympia.amo.storage_utils import copy_stored_file
from olympia.amo.tests import (
    addon_factory, TestCase, user_factory, version_factory)
from olympia.applications.models import AppVersion
from olympia.devhub import tasks, utils
from olympia.files.tasks import repack_fileupload
from olympia.files.tests.test_models import UploadTest
from olympia.scanners.tasks import run_customs, run_wat, run_yara, call_mad_api
from olympia.users.models import (
    EmailUserRestriction, IPNetworkUserRestriction, UserRestrictionHistory)


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

        channel = (amo.RELEASE_CHANNEL_LISTED if listed
                   else amo.RELEASE_CHANNEL_UNLISTED)

        # Make sure we setup the correct validation task.
        self.mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk, channel),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            chord(
                [tasks.forward_linter_results.s(file_upload.pk)],
                call_mad_api.s(file_upload.pk)
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk,
                                                    channel,
                                                    False)
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
        'colors': {
            'frame': '#adb09f',
            'tab_background_text': '#000'
        },
        'images': {
            'theme_frame': 'weta.png'
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


@mock.patch('django_statsd.clients.statsd.incr')
class TestUploadRestrictionChecker(TestCase):
    def setUp(self):
        self.request = RequestFactory(REMOTE_ADDR='10.0.0.1').get('/')
        self.request.is_api = False
        self.request.user = user_factory(read_dev_agreement=self.days_ago(0))
        self.request.user.update(last_login_ip='192.168.1.1')

    def test_is_submission_allowed_pass(self, incr_mock):
        checker = utils.UploadRestrictionChecker(self.request)
        assert checker.is_submission_allowed()
        assert incr_mock.call_count == 1
        assert incr_mock.call_args_list[0][0] == (
            'devhub.is_submission_allowed.success',)
        assert not UserRestrictionHistory.objects.exists()

    def test_is_submission_allowed_hasnt_read_agreement(self, incr_mock):
        self.request.user.update(read_dev_agreement=None)
        checker = utils.UploadRestrictionChecker(self.request)
        assert not checker.is_submission_allowed()
        assert checker.get_error_message() == (
            'Before starting, please read and accept our Firefox Add-on '
            'Distribution Agreement as well as our Review Policies and Rules. '
            'The Firefox Add-on Distribution Agreement also links to our '
            'Privacy Notice which explains how we handle your information.'
        )
        assert incr_mock.call_count == 2
        assert incr_mock.call_args_list[0][0] == (
            'devhub.is_submission_allowed.DeveloperAgreementRestriction'
            '.failure',)
        assert incr_mock.call_args_list[1][0] == (
            'devhub.is_submission_allowed.failure',)
        assert UserRestrictionHistory.objects.count() == 1
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == (
            'DeveloperAgreementRestriction')
        assert history.user == self.request.user
        assert history.last_login_ip == self.request.user.last_login_ip
        assert history.ip_address == '10.0.0.1'

    def test_is_submission_allowed_bypassing_read_dev_agreement(
            self, incr_mock):
        self.request.user.update(read_dev_agreement=None)
        checker = utils.UploadRestrictionChecker(self.request)
        assert checker.is_submission_allowed(check_dev_agreement=False)
        assert incr_mock.call_count == 1
        assert incr_mock.call_args_list[0][0] == (
            'devhub.is_submission_allowed.success',)
        assert not UserRestrictionHistory.objects.exists()

    def test_user_is_allowed_to_bypass_restrictions(self, incr_mock):
        IPNetworkUserRestriction.objects.create(network='10.0.0.0/24')
        self.request.user.update(bypass_upload_restrictions=True)
        checker = utils.UploadRestrictionChecker(self.request)
        assert checker.is_submission_allowed()
        assert not UserRestrictionHistory.objects.exists()
        assert incr_mock.call_count == 0

    def test_is_submission_allowed_ip_restricted(self, incr_mock):
        IPNetworkUserRestriction.objects.create(network='10.0.0.0/24')
        checker = utils.UploadRestrictionChecker(self.request)
        assert not checker.is_submission_allowed()
        assert checker.get_error_message() == (
            'Multiple add-ons violating our policies have been submitted '
            'from your location. The IP address has been blocked.'
        )
        assert incr_mock.call_count == 2
        assert incr_mock.call_args_list[0][0] == (
            'devhub.is_submission_allowed.IPNetworkUserRestriction.failure',)
        assert incr_mock.call_args_list[1][0] == (
            'devhub.is_submission_allowed.failure',)
        assert UserRestrictionHistory.objects.count() == 1
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == 'IPNetworkUserRestriction'
        assert history.user == self.request.user
        assert history.last_login_ip == self.request.user.last_login_ip
        assert history.ip_address == '10.0.0.1'

    def test_is_submission_allowed_email_restricted(self, incr_mock):
        EmailUserRestriction.objects.create(
            email_pattern=self.request.user.email)
        checker = utils.UploadRestrictionChecker(self.request)
        assert not checker.is_submission_allowed()
        assert checker.get_error_message() == (
            'The email address used for your account is not '
            'allowed for add-on submission.'
        )
        assert incr_mock.call_count == 2
        assert incr_mock.call_args_list[0][0] == (
            'devhub.is_submission_allowed.EmailUserRestriction.failure',)
        assert incr_mock.call_args_list[1][0] == (
            'devhub.is_submission_allowed.failure',)
        assert UserRestrictionHistory.objects.count() == 1
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == 'EmailUserRestriction'
        assert history.user == self.request.user
        assert history.last_login_ip == self.request.user.last_login_ip
        assert history.ip_address == '10.0.0.1'


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
            'contains_binary_extension': True,
            'version': '1.0',
            'name': 'gK0Bes Bot',
            'id': 'gkobes@gkobes'
        }
    }
    data = utils.process_validation(results)
    assert not data['errors']
    assert data['ending_tier'] == 5


class TestValidator(UploadTest, TestCase):

    @mock.patch('olympia.devhub.utils.chain')
    def test_appends_final_task_for_file_uploads(self, mock_chain):
        final_task = mock.Mock()
        file_upload = self.get_upload('webextension.xpi',
                                      with_validation=False)
        channel = amo.RELEASE_CHANNEL_LISTED

        utils.Validator(file_upload, listed=True, final_task=final_task)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk, channel),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            chord(
                [tasks.forward_linter_results.s(file_upload.pk)],
                call_mad_api.s(file_upload.pk)
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk,
                                                    channel,
                                                    False),
            final_task,
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_appends_final_task_for_files(self, mock_chain):
        final_task = mock.Mock()
        file = version_factory(addon=addon_factory()).files.get()

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
        file_upload = self.get_upload('webextension.xpi',
                                      with_validation=False)
        channel = amo.RELEASE_CHANNEL_LISTED

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
                call_mad_api.s(file_upload.pk)
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk,
                                                    channel,
                                                    False)
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_does_not_add_run_yara_when_disabled(self, mock_chain):
        self.create_switch('enable-yara', active=False)
        file_upload = self.get_upload('webextension.xpi',
                                      with_validation=False)
        channel = amo.RELEASE_CHANNEL_LISTED

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
            tasks.handle_upload_validation_result.s(file_upload.pk,
                                                    channel,
                                                    False)
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_adds_run_customs_when_enabled(self, mock_chain):
        self.create_switch('enable-customs', active=True)
        file_upload = self.get_upload('webextension.xpi',
                                      with_validation=False)
        channel = amo.RELEASE_CHANNEL_LISTED

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
            tasks.handle_upload_validation_result.s(file_upload.pk,
                                                    channel,
                                                    False)
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_does_not_add_run_customs_when_disabled(self, mock_chain):
        self.create_switch('enable-customs', active=False)
        file_upload = self.get_upload('webextension.xpi',
                                      with_validation=False)
        channel = amo.RELEASE_CHANNEL_LISTED

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
            tasks.handle_upload_validation_result.s(file_upload.pk,
                                                    channel,
                                                    False)
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_adds_run_wat_when_enabled(self, mock_chain):
        self.create_switch('enable-wat', active=True)
        file_upload = self.get_upload('webextension.xpi',
                                      with_validation=False)
        channel = amo.RELEASE_CHANNEL_LISTED

        utils.Validator(file_upload, listed=True)

        mock_chain.assert_called_once_with(
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(file_upload.pk),
            tasks.validate_upload.s(file_upload.pk, channel),
            tasks.check_for_api_keys_in_file.s(file_upload.pk),
            chord(
                [
                    tasks.forward_linter_results.s(file_upload.pk),
                    run_wat.s(file_upload.pk),
                ],
                call_mad_api.s(file_upload.pk),
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk,
                                                    channel,
                                                    False)
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_does_not_add_run_wat_when_disabled(self, mock_chain):
        self.create_switch('enable-wat', active=False)
        file_upload = self.get_upload('webextension.xpi',
                                      with_validation=False)
        channel = amo.RELEASE_CHANNEL_LISTED

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
            tasks.handle_upload_validation_result.s(file_upload.pk,
                                                    channel,
                                                    False)
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_adds_yara_and_customs(self, mock_chain):
        self.create_switch('enable-customs', active=True)
        self.create_switch('enable-yara', active=True)
        file_upload = self.get_upload('webextension.xpi',
                                      with_validation=False)
        channel = amo.RELEASE_CHANNEL_LISTED

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
            tasks.handle_upload_validation_result.s(file_upload.pk,
                                                    channel,
                                                    False)
        )

    @mock.patch('olympia.devhub.utils.chain')
    def test_adds_all_scanners(self, mock_chain):
        self.create_switch('enable-customs', active=True)
        self.create_switch('enable-wat', active=True)
        self.create_switch('enable-yara', active=True)
        file_upload = self.get_upload('webextension.xpi',
                                      with_validation=False)
        channel = amo.RELEASE_CHANNEL_LISTED

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
                    run_wat.s(file_upload.pk),
                ],
                call_mad_api.s(file_upload.pk),
            ),
            tasks.handle_upload_validation_result.s(file_upload.pk,
                                                    channel,
                                                    False)
        )

    def test_create_file_upload_tasks(self):
        self.create_switch('enable-customs', active=True)
        self.create_switch('enable-wat', active=True)
        self.create_switch('enable-yara', active=True)
        file_upload = self.get_upload(
            'webextension.xpi', with_validation=False
        )
        channel = amo.RELEASE_CHANNEL_LISTED
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
            'olympia.scanners.tasks.run_wat',
        ]
        assert len(scanners_chord.tasks) == len(expected_parallel_tasks)
        assert (expected_parallel_tasks == [task.name for task in
                                            scanners_chord.tasks])
        # Callback
        assert (
            scanners_chord.body.name == 'olympia.scanners.tasks.call_mad_api'
        )
