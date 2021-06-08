from contextlib import ExitStack
from unittest import mock
import pytest

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.forms import ValidationError
from django.test.client import RequestFactory

from olympia.addons.utils import (
    get_addon_recommendations,
    get_addon_recommendations_invalid,
    is_outcome_recommended,
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
            user=self.request.user, ip_address='10.0.0.2'
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
            user=self.request.user, ip_address='10.0.0.2'
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
            user=self.request.user, ip_address='10.0.0.2'
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
