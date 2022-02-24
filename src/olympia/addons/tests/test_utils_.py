from contextlib import ExitStack
from unittest import mock
import pytest
import zipfile

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.forms import ValidationError
from django.test.client import RequestFactory

from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.utils import (
    get_addon_recommendations,
    get_addon_recommendations_invalid,
    is_outcome_recommended,
    SitePermissionVersionCreator,
    RestrictionChecker,
    TAAR_LITE_FALLBACK_REASON_EMPTY,
    TAAR_LITE_FALLBACK_REASON_TIMEOUT,
    TAAR_LITE_FALLBACKS,
    TAAR_LITE_OUTCOME_CURATED,
    TAAR_LITE_OUTCOME_REAL_FAIL,
    TAAR_LITE_OUTCOME_REAL_SUCCESS,
    TAAR_LITE_FALLBACK_REASON_INVALID,
    verify_mozilla_trademark,
)
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.applications.models import AppVersion
from olympia.constants.site_permissions import SITE_PERMISSION_MIN_VERSION
from olympia.files.models import FileUpload
from olympia.users.models import (
    EmailUserRestriction,
    Group,
    GroupUser,
    IPNetworkUserRestriction,
    RESTRICTION_TYPES,
    UserRestrictionHistory,
)


@pytest.mark.django_db
@pytest.mark.parametrize(
    'name, allowed, give_permission',
    (
        ('Fancy new Add-on', True, False),
        # We allow the 'for ...' postfix to be used
        ('Fancy new Add-on for Firefox', True, False),
        ('Fancy new Add-on for Mozilla', True, False),
        # But only the postfix
        ('Fancy new Add-on for Firefox Browser', False, False),
        ('For Firefox fancy new add-on', False, False),
        # But users with the TRADEMARK_BYPASS permission are allowed
        ('Firefox makes everything better', False, False),
        ('Firefox makes everything better', True, True),
        ('Mozilla makes everything better', True, True),
        # A few more test-cases...
        ('Firefox add-on for Firefox', False, False),
        ('Firefox add-on for Firefox', True, True),
        ('Foobarfor Firefox', False, False),
        ('Better Privacy for Firefox!', True, False),
        ('Firefox awesome for Mozilla', False, False),
        ('Firefox awesome for Mozilla', True, True),
    ),
)
def test_verify_mozilla_trademark(name, allowed, give_permission):
    user = user_factory()
    if give_permission:
        group = Group.objects.create(name=name, rules='Trademark:Bypass')
        GroupUser.objects.create(group=group, user=user)

    if not allowed:
        with pytest.raises(ValidationError) as exc:
            verify_mozilla_trademark(name, user)
        assert exc.value.message == (
            'Add-on names cannot contain the Mozilla or Firefox trademarks.'
        )
    else:
        verify_mozilla_trademark(name, user)


class TestGetAddonRecommendations(TestCase):
    def setUp(self):
        patcher = mock.patch('olympia.addons.utils.call_recommendation_server')
        self.recommendation_server_mock = patcher.start()
        self.addCleanup(patcher.stop)
        self.a101 = addon_factory(id=101, guid='101@mozilla')
        addon_factory(id=102, guid='102@mozilla')
        addon_factory(id=103, guid='103@mozilla')
        addon_factory(id=104, guid='104@mozilla')

        self.recommendation_guids = [
            '101@mozilla',
            '102@mozilla',
            '103@mozilla',
            '104@mozilla',
        ]
        self.recommendation_server_mock.return_value = self.recommendation_guids

    def test_recommended(self):
        recommendations, outcome, reason = get_addon_recommendations('a@b', True)
        assert recommendations == self.recommendation_guids
        assert outcome == TAAR_LITE_OUTCOME_REAL_SUCCESS
        assert reason is None
        self.recommendation_server_mock.assert_called_with(
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, 'a@b', {}
        )

    def test_recommended_no_results(self):
        self.recommendation_server_mock.return_value = []
        recommendations, outcome, reason = get_addon_recommendations('a@b', True)
        assert recommendations == TAAR_LITE_FALLBACKS
        assert outcome == TAAR_LITE_OUTCOME_REAL_FAIL
        assert reason is TAAR_LITE_FALLBACK_REASON_EMPTY
        self.recommendation_server_mock.assert_called_with(
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, 'a@b', {}
        )

    def test_recommended_timeout(self):
        self.recommendation_server_mock.return_value = None
        recommendations, outcome, reason = get_addon_recommendations('a@b', True)
        assert recommendations == TAAR_LITE_FALLBACKS
        assert outcome == TAAR_LITE_OUTCOME_REAL_FAIL
        assert reason is TAAR_LITE_FALLBACK_REASON_TIMEOUT
        self.recommendation_server_mock.assert_called_with(
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, 'a@b', {}
        )

    def test_not_recommended(self):
        recommendations, outcome, reason = get_addon_recommendations('a@b', False)
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


@mock.patch('django_statsd.clients.statsd.incr')
class TestRestrictionChecker(TestCase):
    def setUp(self):
        self.request = RequestFactory(REMOTE_ADDR='10.0.0.1').get('/')
        self.request.is_api = False
        self.request.user = user_factory(read_dev_agreement=self.days_ago(0))
        self.request.user.update(last_login_ip='192.168.1.1')

    def test_is_submission_allowed_pass(self, incr_mock):
        checker = RestrictionChecker(request=self.request)
        assert checker.is_submission_allowed()
        assert incr_mock.call_count == 1
        assert incr_mock.call_args_list[0][0] == (
            'RestrictionChecker.is_submission_allowed.success',
        )
        assert not UserRestrictionHistory.objects.exists()

    def test_is_submission_allowed_hasnt_read_agreement(self, incr_mock):
        self.request.user.update(read_dev_agreement=None)
        checker = RestrictionChecker(request=self.request)
        assert not checker.is_submission_allowed()
        assert checker.get_error_message() == (
            'Before starting, please read and accept our Firefox Add-on '
            'Distribution Agreement as well as our Review Policies and Rules. '
            'The Firefox Add-on Distribution Agreement also links to our '
            'Privacy Notice which explains how we handle your information.'
        )
        assert incr_mock.call_count == 2
        assert incr_mock.call_args_list[0][0] == (
            'RestrictionChecker.is_submission_allowed.DeveloperAgreementRestriction.'
            'failure',
        )
        assert incr_mock.call_args_list[1][0] == (
            'RestrictionChecker.is_submission_allowed.failure',
        )
        assert UserRestrictionHistory.objects.count() == 1
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == ('DeveloperAgreementRestriction')
        assert history.user == self.request.user
        assert history.last_login_ip == self.request.user.last_login_ip
        assert history.ip_address == '10.0.0.1'

    def test_is_submission_allowed_bypassing_read_dev_agreement(self, incr_mock):
        self.request.user.update(read_dev_agreement=None)
        checker = RestrictionChecker(request=self.request)
        assert checker.is_submission_allowed(check_dev_agreement=False)
        assert incr_mock.call_count == 1
        assert incr_mock.call_args_list[0][0] == (
            'RestrictionChecker.is_submission_allowed.success',
        )
        assert not UserRestrictionHistory.objects.exists()

    def test_user_is_allowed_to_bypass_restrictions(self, incr_mock):
        IPNetworkUserRestriction.objects.create(network='10.0.0.0/24')
        EmailUserRestriction.objects.create(email_pattern=self.request.user.email)
        self.request.user.update(bypass_upload_restrictions=True)
        checker = RestrictionChecker(request=self.request)
        assert checker.is_submission_allowed()
        assert not UserRestrictionHistory.objects.exists()
        assert incr_mock.call_count == 0

    def test_is_submission_allowed_ip_restricted(self, incr_mock):
        IPNetworkUserRestriction.objects.create(network='10.0.0.0/24')
        checker = RestrictionChecker(request=self.request)
        assert not checker.is_submission_allowed()
        assert checker.get_error_message() == (
            'Multiple add-ons violating our policies have been submitted '
            'from your location. The IP address has been blocked.'
        )
        assert incr_mock.call_count == 2
        assert incr_mock.call_args_list[0][0] == (
            'RestrictionChecker.is_submission_allowed.IPNetworkUserRestriction.failure',
        )
        assert incr_mock.call_args_list[1][0] == (
            'RestrictionChecker.is_submission_allowed.failure',
        )
        assert UserRestrictionHistory.objects.count() == 1
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == 'IPNetworkUserRestriction'
        assert history.user == self.request.user
        assert history.last_login_ip == self.request.user.last_login_ip
        assert history.ip_address == '10.0.0.1'

    def test_is_submission_allowed_email_restricted(self, incr_mock):
        EmailUserRestriction.objects.create(email_pattern=self.request.user.email)
        checker = RestrictionChecker(request=self.request)
        assert not checker.is_submission_allowed()
        assert checker.get_error_message() == (
            'The email address used for your account is not '
            'allowed for add-on submission.'
        )
        assert incr_mock.call_count == 2
        assert incr_mock.call_args_list[0][0] == (
            'RestrictionChecker.is_submission_allowed.EmailUserRestriction.failure',
        )
        assert incr_mock.call_args_list[1][0] == (
            'RestrictionChecker.is_submission_allowed.failure',
        )
        assert UserRestrictionHistory.objects.count() == 1
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == 'EmailUserRestriction'
        assert history.user == self.request.user
        assert history.last_login_ip == self.request.user.last_login_ip
        assert history.ip_address == '10.0.0.1'

    def test_is_submission_allowed_bypassing_read_dev_agreement_restricted(
        self, incr_mock
    ):
        # Mix of test_is_submission_allowed_email_restricted() and
        # test_is_submission_allowed_bypassing_read_dev_agreement() above:
        # this time, we're restricted by email while bypassing the read dev
        # agreement check. This ensures even when bypassing that check, we
        # still record everything properly when restricting.
        EmailUserRestriction.objects.create(email_pattern=self.request.user.email)
        checker = RestrictionChecker(request=self.request)
        assert not checker.is_submission_allowed(check_dev_agreement=False)
        assert checker.get_error_message() == (
            'The email address used for your account is not '
            'allowed for add-on submission.'
        )
        assert incr_mock.call_count == 2
        assert incr_mock.call_args_list[0][0] == (
            'RestrictionChecker.is_submission_allowed.EmailUserRestriction.failure',
        )
        assert incr_mock.call_args_list[1][0] == (
            'RestrictionChecker.is_submission_allowed.failure',
        )
        assert UserRestrictionHistory.objects.count() == 1
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == 'EmailUserRestriction'
        assert history.user == self.request.user
        assert history.last_login_ip == self.request.user.last_login_ip
        assert history.ip_address == '10.0.0.1'

    def test_is_auto_approval_allowed_email_restricted_only_for_submission(
        self, incr_mock
    ):
        # Test with a submission restriction (the default): approval should be allowed.
        EmailUserRestriction.objects.create(email_pattern=self.request.user.email)
        upload = FileUpload.objects.create(
            user=self.request.user,
            ip_address='10.0.0.2',
            source=amo.UPLOAD_SOURCE_DEVHUB,
        )
        incr_mock.reset_mock()
        checker = RestrictionChecker(upload=upload)
        assert checker.is_auto_approval_allowed()
        assert incr_mock.call_count == 1
        assert UserRestrictionHistory.objects.count() == 0
        assert incr_mock.call_args_list[0][0] == (
            'RestrictionChecker.is_auto_approval_allowed.success',
        )

    def test_is_auto_approval_allowed_email_restricted(self, incr_mock):
        EmailUserRestriction.objects.create(
            email_pattern=self.request.user.email,
            restriction_type=RESTRICTION_TYPES.APPROVAL,
        )
        upload = FileUpload.objects.create(
            user=self.request.user,
            ip_address='10.0.0.2',
            source=amo.UPLOAD_SOURCE_DEVHUB,
        )
        incr_mock.reset_mock()
        checker = RestrictionChecker(upload=upload)
        assert not checker.is_auto_approval_allowed()
        assert incr_mock.call_count == 2
        assert incr_mock.call_args_list[0][0] == (
            'RestrictionChecker.is_auto_approval_allowed.EmailUserRestriction.failure',
        )
        assert incr_mock.call_args_list[1][0] == (
            'RestrictionChecker.is_auto_approval_allowed.failure',
        )
        assert UserRestrictionHistory.objects.count() == 1
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == 'EmailUserRestriction'
        assert history.user == self.request.user
        assert history.last_login_ip == self.request.user.last_login_ip
        assert history.ip_address == '10.0.0.2'

    def test_no_request_or_upload_at_init(self, incr_mock):
        with self.assertRaises(ImproperlyConfigured):
            RestrictionChecker()

    def test_is_submission_allowed_no_request_raises_improperly_configured(
        self, incr_mock
    ):
        checker = RestrictionChecker(upload=mock.Mock())
        with self.assertRaises(ImproperlyConfigured):
            assert checker.is_submission_allowed()

    def test_is_auto_approval_allowed_no_upload_raises_improperly_configured(
        self, incr_mock
    ):
        checker = RestrictionChecker(request=self.request)
        with self.assertRaises(ImproperlyConfigured):
            assert checker.is_auto_approval_allowed()

    def test_is_submission_allowed_with_mocks(self, incr_mock):
        checker = RestrictionChecker(request=self.request)
        with ExitStack() as stack:
            allow_submission_mocks = [
                stack.enter_context(mock.patch.object(choice[1], 'allow_submission'))
                for choice in checker.restriction_choices
            ]
            allow_auto_approval_mocks = [
                stack.enter_context(mock.patch.object(choice[1], 'allow_auto_approval'))
                for choice in checker.restriction_choices
            ]
            assert checker.is_submission_allowed()
        for restriction_mock in allow_submission_mocks:
            assert restriction_mock.call_count == 1
        for restriction_mock in allow_auto_approval_mocks:
            assert restriction_mock.call_count == 0

    def test_is_auto_approval_allowed_with_mocks(self, incr_mock):
        upload = FileUpload.objects.create(
            user=self.request.user,
            ip_address='10.0.0.2',
            source=amo.UPLOAD_SOURCE_DEVHUB,
        )
        checker = RestrictionChecker(upload=upload)
        with ExitStack() as stack:
            allow_submission_mocks = [
                stack.enter_context(mock.patch.object(choice[1], 'allow_submission'))
                for choice in checker.restriction_choices
            ]
            allow_auto_approval_mocks = [
                stack.enter_context(mock.patch.object(choice[1], 'allow_auto_approval'))
                for choice in checker.restriction_choices
            ]
            assert checker.is_auto_approval_allowed()
        for restriction_mock in allow_submission_mocks:
            assert restriction_mock.call_count == 0
        for restriction_mock in allow_auto_approval_mocks:
            assert restriction_mock.call_count == 1


class TestSitePermissionVersionCreator(TestCase):
    def setUp(self):
        self.task_user = user_factory(pk=settings.TASK_USER_ID)
        for app in ['firefox', 'android']:
            AppVersion.objects.get_or_create(
                application=amo.APPS[app].id,
                version=SITE_PERMISSION_MIN_VERSION,
            )
            AppVersion.objects.get_or_create(
                application=amo.APPS[app].id,
                version='*',
            )

    def test_create_manifest_single_origin_single_permission(self):
        creator = SitePermissionVersionCreator(
            user=user_factory(),
            remote_addr='4.8.15.16',
            install_origins=['https://example.com'],
            site_permissions=['midi-sysex'],
        )
        manifest_data = creator._create_manifest('1.0')
        guid = (
            manifest_data.get('browser_specific_settings', {})
            .get('gecko', {})
            .get('id')
        )
        assert guid
        assert manifest_data == {
            'browser_specific_settings': {
                'gecko': {'id': guid, 'strict_min_version': '97.0'}
            },
            'install_origins': ['https://example.com'],
            'manifest_version': 2,
            'name': 'Site permissions for example.com',
            'site_permissions': ['midi-sysex'],
            'version': '1.0',
        }

    def test_create_manifest_multiple_origins_and_permissions(self):
        creator = SitePermissionVersionCreator(
            user=user_factory(),
            remote_addr='4.8.15.16',
            install_origins=['https://example.com', 'https://foo.com'],
            site_permissions=['midi-sysex', 'webblah'],
        )
        manifest_data = creator._create_manifest('2.0')
        guid = (
            manifest_data.get('browser_specific_settings', {})
            .get('gecko', {})
            .get('id')
        )
        assert guid
        assert manifest_data == {
            'browser_specific_settings': {
                'gecko': {'id': guid, 'strict_min_version': '97.0'}
            },
            'install_origins': ['https://example.com', 'https://foo.com'],
            'manifest_version': 2,
            'name': 'Site permissions for example.com, foo.com',
            'site_permissions': ['midi-sysex', 'webblah'],
            'version': '2.0',
        }

    def test_create_manifest_with_guid(self):
        creator = SitePermissionVersionCreator(
            user=user_factory(),
            remote_addr='4.8.15.16',
            install_origins=['https://example.com'],
            site_permissions=['midi-sysex'],
        )
        manifest_data = creator._create_manifest('1.0', 'some@guid')
        guid = (
            manifest_data.get('browser_specific_settings', {})
            .get('gecko', {})
            .get('id')
        )
        assert guid == 'some@guid'
        assert manifest_data == {
            'browser_specific_settings': {
                'gecko': {'id': guid, 'strict_min_version': '97.0'}
            },
            'install_origins': ['https://example.com'],
            'manifest_version': 2,
            'name': 'Site permissions for example.com',
            'site_permissions': ['midi-sysex'],
            'version': '1.0',
        }

    def test_create_zipfile(self):
        creator = SitePermissionVersionCreator(
            user=None,
            remote_addr=None,
            install_origins=None,
            site_permissions=None,
        )
        file_obj = creator._create_zipfile({'foo': 'bar'})
        assert file_obj.name == 'automatic.xpi'
        assert file_obj.size
        zip_file = zipfile.ZipFile(file_obj)
        assert zip_file.namelist() == ['manifest.json']
        manifest_contents = zipfile.ZipFile(file_obj).read('manifest.json')
        assert manifest_contents == b'{\n  "foo": "bar"\n}'

    @override_switch('record-install-origins', active=True)
    def test_create_version_no_addon(self):
        creator = SitePermissionVersionCreator(
            user=user_factory(),
            remote_addr='4.8.15.16',
            install_origins=['https://example.com', 'https://foo.com'],
            site_permissions=['midi-sysex', 'webblah'],
        )
        version = creator.create_version()
        assert version
        addon = version.addon
        file_ = version.file
        # Reload to ensure everything was saved in database correctly.
        version.reload()
        addon.reload()
        file_.reload()
        assert version.pk
        assert version.channel == amo.RELEASE_CHANNEL_UNLISTED
        assert version.version == '1.0'
        assert sorted(
            version.installorigin_set.all().values_list('origin', flat=True)
        ) == [
            'https://example.com',
            'https://foo.com',
        ]
        assert addon.pk
        assert addon.guid
        assert addon.status == amo.STATUS_NULL
        assert addon.type == amo.ADDON_SITE_PERMISSION
        assert list(addon.authors.all()) == [creator.user]
        assert file_.status == amo.STATUS_AWAITING_REVIEW
        assert file_._site_permissions
        assert file_._site_permissions.permissions == ['midi-sysex', 'webblah']
        activity = ActivityLog.objects.for_addons(addon).latest('pk')
        assert activity.user == creator.user
        assert activity.iplog_set.all()[0].ip_address == '4.8.15.16'

    @override_switch('record-install-origins', active=True)
    def test_create_version_existing_addon_wrong_origins(self):
        creator = SitePermissionVersionCreator(
            user=user_factory(),
            remote_addr='4.8.15.16',
            install_origins=['https://example.com', 'https://foo.com'],
            site_permissions=['midi-sysex', 'webblah'],
        )
        addon = addon_factory(
            version_kw={'version': '1.0'},
            type=amo.ADDON_SITE_PERMISSION,
            users=[creator.user],
        )
        initial_version = addon.versions.get()
        self.make_addon_unlisted(addon)
        with self.assertRaises(ImproperlyConfigured):
            creator.create_version(addon=addon)

        # Both need to match, not just one.
        initial_version.installorigin_set.create(origin='https://example.com')
        with self.assertRaises(ImproperlyConfigured):
            creator.create_version(addon=addon)

    @override_switch('record-install-origins', active=True)
    def test_create_version_existing_addon(self):
        creator = SitePermissionVersionCreator(
            user=user_factory(),
            remote_addr='4.8.15.16',
            install_origins=['https://example.com', 'https://foo.com'],
            site_permissions=['midi-sysex', 'webblah'],
        )
        addon = addon_factory(
            version_kw={'version': '1.0'},
            type=amo.ADDON_SITE_PERMISSION,
            users=[creator.user],
        )
        initial_version = addon.versions.get()
        initial_version.installorigin_set.create(origin='https://foo.com')
        initial_version.installorigin_set.create(origin='https://example.com')
        self.make_addon_unlisted(addon)
        version = creator.create_version(addon=addon)
        assert version
        assert version != initial_version
        assert version.addon == addon
        file_ = version.file
        # Reload to ensure everything was saved in database correctly.
        version.reload()
        addon.reload()
        file_.reload()
        assert version.pk
        assert version.channel == amo.RELEASE_CHANNEL_UNLISTED
        assert version.version == '2.0'
        assert sorted(
            version.installorigin_set.all().values_list('origin', flat=True)
        ) == [
            'https://example.com',
            'https://foo.com',
        ]
        assert addon.pk
        assert addon.status == amo.STATUS_NULL
        assert addon.type == amo.ADDON_SITE_PERMISSION
        assert list(addon.authors.all()) == [creator.user]
        assert file_.status == amo.STATUS_AWAITING_REVIEW
        assert file_._site_permissions
        assert file_._site_permissions.permissions == ['midi-sysex', 'webblah']
        activity = ActivityLog.objects.for_addons(addon).latest('pk')
        assert activity.user == creator.user
        assert activity.iplog_set.all()[0].ip_address == '4.8.15.16'

    def test_create_version_existing_addon_but_user_is_not_an_author(self):
        creator = SitePermissionVersionCreator(
            user=user_factory(),
            remote_addr='4.8.15.16',
            install_origins=['https://example.com', 'https://foo.com'],
            site_permissions=['midi-sysex', 'webblah'],
        )
        addon = addon_factory(
            version_kw={'version': '1.0'},
            type=amo.ADDON_SITE_PERMISSION,
            users=[user_factory()],
        )
        self.make_addon_unlisted(addon)
        with self.assertRaises(ImproperlyConfigured):
            creator.create_version(addon=addon)
