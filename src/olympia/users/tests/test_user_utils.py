import json
from contextlib import ExitStack
from ipaddress import IPv4Address
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.test.client import RequestFactory

import pytest
import responses
import time_machine

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.amo.tests import TestCase, user_factory
from olympia.files.models import FileUpload

from ..models import (
    RESTRICTION_TYPES,
    AsnUserRestriction,
    EmailUserRestriction,
    FingerprintRestriction,
    IPNetworkUserRestriction,
    SuppressedEmail,
    SuppressedEmailVerification,
    UserRestrictionHistory,
)
from ..utils import (
    RestrictionChecker,
    UnsubscribeCode,
    check_suppressed_email_confirmation,
)


def test_email_unsubscribe_code_parse():
    email = 'nobody@mozîlla.org'
    token, hash_ = UnsubscribeCode.create(email)

    r_email = UnsubscribeCode.parse(token, hash_)
    assert email == r_email

    # A bad token or hash raises ValueError
    with pytest.raises(ValueError):
        UnsubscribeCode.parse(token, hash_[:-5])
    with pytest.raises(ValueError):
        UnsubscribeCode.parse(token[5:], hash_)


@mock.patch('django_statsd.clients.statsd.incr')
class TestRestrictionChecker(TestCase):
    def setUp(self):
        self.ja4 = 'd1234-5678-0000'
        self.asn = 64497
        headers = {
            'Client-JA4': self.ja4,
            'X-SigSci-Tags': 'TAG,ANOTHERTAG',
            'Asn': str(self.asn),
        }
        self.request = RequestFactory(REMOTE_ADDR='10.0.0.1', headers=headers).get('/')
        self.request.is_api = False
        self.request.user = user_factory(read_dev_agreement=self.days_ago(0))
        self.request.user.update(last_login_ip='192.168.1.1')
        core.set_remote_addr(self.request.META.get('REMOTE_ADDR'))

    def test_is_submission_allowed_pass(self, incr_mock):
        checker = RestrictionChecker(request=self.request)
        assert checker.is_submission_allowed()
        assert incr_mock.call_count == 1
        assert incr_mock.call_args_list[0][0] == (
            'RestrictionChecker.is_submission_allowed.success',
        )
        assert not UserRestrictionHistory.objects.exists()
        assert not ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).exists()

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
        assert ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).count() == 1
        activity = ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).get()
        assert activity.user == self.request.user
        assert activity.iplog.ip_address_binary == IPv4Address('10.0.0.1')
        assert activity.iplog.asn == self.asn
        assert activity.requestfingerprintlog.ja4 == self.ja4
        assert activity.requestfingerprintlog.signals == ['TAG', 'ANOTHERTAG']

    def test_is_submission_allowed_bypassing_read_dev_agreement(self, incr_mock):
        self.request.user.update(read_dev_agreement=None)
        checker = RestrictionChecker(request=self.request)
        assert checker.is_submission_allowed(check_dev_agreement=False)
        assert incr_mock.call_count == 1
        assert incr_mock.call_args_list[0][0] == (
            'RestrictionChecker.is_submission_allowed.success',
        )
        assert not UserRestrictionHistory.objects.exists()
        assert not ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).exists()

    def test_user_is_allowed_to_bypass_restrictions(self, incr_mock):
        IPNetworkUserRestriction.objects.create(network='10.0.0.0/24')
        EmailUserRestriction.objects.create(email_pattern=self.request.user.email)
        self.request.user.update(bypass_upload_restrictions=True)
        checker = RestrictionChecker(request=self.request)
        assert checker.is_submission_allowed()
        assert not UserRestrictionHistory.objects.exists()
        assert incr_mock.call_count == 0

    def test_is_submission_allowed_ip_restricted(self, incr_mock):
        restriction = IPNetworkUserRestriction.objects.create(network='10.0.0.0/24')
        checker = RestrictionChecker(request=self.request)
        assert not checker.is_submission_allowed()
        assert checker.get_error_message() == (
            'Multiple submissions violating our policies have been sent '
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
        assert history.restriction_instance == restriction
        assert history.version is None
        assert ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).count() == 1
        activity = ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).get()
        assert activity.user == self.request.user
        assert activity.iplog.ip_address_binary == IPv4Address('10.0.0.1')
        assert activity.iplog.asn == self.asn
        assert activity.requestfingerprintlog.ja4 == self.ja4
        assert activity.requestfingerprintlog.signals == ['TAG', 'ANOTHERTAG']

    def test_is_submission_allowed_email_restricted(self, incr_mock):
        restriction = EmailUserRestriction.objects.create(
            email_pattern=self.request.user.email
        )
        checker = RestrictionChecker(request=self.request)
        assert not checker.is_submission_allowed()
        assert checker.get_error_message() == (
            'The email address used for your account is not allowed for submissions.'
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
        assert history.restriction_instance == restriction
        assert history.version is None
        assert ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).count() == 1
        activity = ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).get()
        assert activity.user == self.request.user
        assert activity.iplog.ip_address_binary == IPv4Address('10.0.0.1')
        assert activity.iplog.asn == self.asn
        assert activity.requestfingerprintlog.ja4 == self.ja4
        assert activity.requestfingerprintlog.signals == ['TAG', 'ANOTHERTAG']

    def test_is_submission_allowed_ja4_restricted(self, incr_mock):
        restriction = FingerprintRestriction.objects.create(ja4=self.ja4)
        checker = RestrictionChecker(request=self.request)
        assert not checker.is_submission_allowed()
        assert checker.get_error_message() == (
            'The software or device you are using is not allowed for submissions.'
        )
        assert incr_mock.call_count == 2
        assert incr_mock.call_args_list[0][0] == (
            'RestrictionChecker.is_submission_allowed.FingerprintRestriction.failure',
        )
        assert incr_mock.call_args_list[1][0] == (
            'RestrictionChecker.is_submission_allowed.failure',
        )
        assert UserRestrictionHistory.objects.count() == 1
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == 'FingerprintRestriction'
        assert history.user == self.request.user
        assert history.last_login_ip == self.request.user.last_login_ip
        assert history.ip_address == '10.0.0.1'
        assert history.restriction_instance == restriction
        assert history.version is None
        assert ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).count() == 1
        activity = ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).get()
        assert activity.user == self.request.user
        assert activity.iplog.ip_address_binary == IPv4Address('10.0.0.1')
        assert activity.iplog.asn == self.asn
        assert activity.requestfingerprintlog.ja4 == self.ja4
        assert activity.requestfingerprintlog.signals == ['TAG', 'ANOTHERTAG']

    def test_is_submission_allowed_asn_restricted(self, incr_mock):
        restriction = AsnUserRestriction.objects.create(asn=self.asn)
        checker = RestrictionChecker(request=self.request)
        assert not checker.is_submission_allowed()
        assert checker.get_error_message() == (
            'Multiple submissions violating our policies have been sent '
            'from your location. The IP address has been blocked.'
        )
        assert incr_mock.call_count == 2
        assert incr_mock.call_args_list[0][0] == (
            'RestrictionChecker.is_submission_allowed.AsnUserRestriction.failure',
        )
        assert incr_mock.call_args_list[1][0] == (
            'RestrictionChecker.is_submission_allowed.failure',
        )
        assert UserRestrictionHistory.objects.count() == 1
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == 'AsnUserRestriction'
        assert history.user == self.request.user
        assert history.last_login_ip == self.request.user.last_login_ip
        assert history.ip_address == '10.0.0.1'
        assert history.restriction_instance == restriction
        assert history.version is None
        assert ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).count() == 1
        activity = ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).get()
        assert activity.user == self.request.user
        assert activity.iplog.ip_address_binary == IPv4Address('10.0.0.1')
        assert activity.iplog.asn == self.asn
        assert activity.requestfingerprintlog.ja4 == self.ja4
        assert activity.requestfingerprintlog.signals == ['TAG', 'ANOTHERTAG']

    def test_is_submission_allowed_bypassing_read_dev_agreement_restricted(
        self, incr_mock
    ):
        # Mix of test_is_submission_allowed_email_restricted() and
        # test_is_submission_allowed_bypassing_read_dev_agreement() above:
        # this time, we're restricted by email while bypassing the read dev
        # agreement check. This ensures even when bypassing that check, we
        # still record everything properly when restricting.
        restriction = EmailUserRestriction.objects.create(
            email_pattern=self.request.user.email
        )
        checker = RestrictionChecker(request=self.request)
        assert not checker.is_submission_allowed(check_dev_agreement=False)
        assert checker.get_error_message() == (
            'The email address used for your account is not allowed for submissions.'
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
        assert history.restriction_instance == restriction
        assert history.version is None
        assert ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).count() == 1
        activity = ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).get()
        assert activity.user == self.request.user
        assert activity.iplog.ip_address_binary == IPv4Address('10.0.0.1')
        assert activity.iplog.asn == self.asn
        assert activity.requestfingerprintlog.ja4 == self.ja4
        assert activity.requestfingerprintlog.signals == ['TAG', 'ANOTHERTAG']

    def test_is_auto_approval_allowed_email_restricted_only_for_submission(
        self, incr_mock
    ):
        # Test with a submission restriction (the default): approval should be allowed.
        EmailUserRestriction.objects.create(email_pattern=self.request.user.email)
        upload = FileUpload.objects.create(
            user=self.request.user,
            ip_address='10.0.0.2',
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        incr_mock.reset_mock()
        checker = RestrictionChecker(upload=upload)
        assert checker.is_auto_approval_allowed()
        assert incr_mock.call_count == 1
        assert UserRestrictionHistory.objects.count() == 0
        assert not ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).exists()
        assert incr_mock.call_args_list[0][0] == (
            'RestrictionChecker.is_auto_approval_allowed.success',
        )

    def test_is_auto_approval_allowed_email_restricted(self, incr_mock):
        restriction = EmailUserRestriction.objects.create(
            email_pattern=self.request.user.email,
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL,
        )
        upload = FileUpload.objects.create(
            user=self.request.user,
            ip_address='10.0.0.2',
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
            request_metadata={
                'Asn': self.asn,
                'Client-JA4': 'd1234-5678-0002',
                'X-SigSci-Tags': 'TAG2,ANOTHERTAG2',
            },
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
        assert history.restriction_instance == restriction
        assert history.version is None
        assert ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).count() == 1
        activity = ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).get()
        assert activity.user == self.request.user
        # Note that there is no request in this case, the ip_address is coming
        # from the upload.
        assert activity.iplog.ip_address_binary == IPv4Address('10.0.0.2')
        assert activity.iplog.asn == self.asn
        assert activity.requestfingerprintlog.ja4 == 'd1234-5678-0002'
        assert activity.requestfingerprintlog.signals == ['TAG2', 'ANOTHERTAG2']

    def test_is_auto_approval_allowed_ja4_restricted(self, incr_mock):
        restriction = FingerprintRestriction.objects.create(
            ja4=self.ja4,
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL,
        )
        upload = FileUpload.objects.create(
            user=self.request.user,
            ip_address='10.0.0.2',
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
            request_metadata={
                'Asn': self.asn,
                'Client-JA4': self.ja4,
                'X-SigSci-Tags': 'TAG2,ANOTHERTAG2',
            },
        )
        incr_mock.reset_mock()
        checker = RestrictionChecker(upload=upload)
        assert not checker.is_auto_approval_allowed()
        assert incr_mock.call_count == 2
        assert incr_mock.call_args_list[0][0] == (
            'RestrictionChecker.is_auto_approval_allowed.FingerprintRestriction.failure',
        )
        assert incr_mock.call_args_list[1][0] == (
            'RestrictionChecker.is_auto_approval_allowed.failure',
        )
        assert UserRestrictionHistory.objects.count() == 1
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == 'FingerprintRestriction'
        assert history.user == self.request.user
        assert history.last_login_ip == self.request.user.last_login_ip
        assert history.ip_address == '10.0.0.2'
        assert history.restriction_instance == restriction
        assert history.version is None
        assert ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).count() == 1
        activity = ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).get()
        assert activity.user == self.request.user
        # Note that there is no request in this case, the ip_address is coming
        # from the upload.
        assert activity.iplog.ip_address_binary == IPv4Address('10.0.0.2')
        assert activity.iplog.asn == self.asn
        assert activity.requestfingerprintlog.ja4 == self.ja4
        assert activity.requestfingerprintlog.signals == ['TAG2', 'ANOTHERTAG2']

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
                for choice in UserRestrictionHistory.RESTRICTION_CLASSES_CHOICES
            ]
            allow_auto_approval_mocks = [
                stack.enter_context(mock.patch.object(choice[1], 'allow_auto_approval'))
                for choice in UserRestrictionHistory.RESTRICTION_CLASSES_CHOICES
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
            channel=amo.CHANNEL_LISTED,
        )
        checker = RestrictionChecker(upload=upload)
        with ExitStack() as stack:
            allow_submission_mocks = [
                stack.enter_context(mock.patch.object(choice[1], 'allow_submission'))
                for choice in UserRestrictionHistory.RESTRICTION_CLASSES_CHOICES
            ]
            allow_auto_approval_mocks = [
                stack.enter_context(mock.patch.object(choice[1], 'allow_auto_approval'))
                for choice in UserRestrictionHistory.RESTRICTION_CLASSES_CHOICES
            ]
            assert checker.is_auto_approval_allowed()
        for restriction_mock in allow_submission_mocks:
            assert restriction_mock.call_count == 0
        for restriction_mock in allow_auto_approval_mocks:
            assert restriction_mock.call_count == 1

    def test_history_records_matched_instance_on_submission(self, incr_mock):
        restriction = EmailUserRestriction.objects.create(
            email_pattern=self.request.user.email
        )
        checker = RestrictionChecker(request=self.request)
        assert not checker.is_submission_allowed()
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == 'EmailUserRestriction'
        assert history.restriction_instance == restriction
        assert history.restriction_content_type == ContentType.objects.get_for_model(
            EmailUserRestriction
        )
        assert history.restriction_object_id == restriction.pk
        assert history.version is None
        assert checker.history_entries == [history]

    def test_history_one_row_per_matched_instance(self, incr_mock):
        exact = IPNetworkUserRestriction.objects.create(network='10.0.0.1/32')
        subnet = IPNetworkUserRestriction.objects.create(network='10.0.0.0/24')
        checker = RestrictionChecker(request=self.request)
        assert not checker.is_submission_allowed()
        entries = UserRestrictionHistory.objects.filter(user=self.request.user)
        assert entries.count() == 2
        assert {entry.restriction_instance for entry in entries} == {exact, subnet}
        for entry in entries:
            assert entry.get_restriction_display() == 'IPNetworkUserRestriction'
            assert entry.ip_address == '10.0.0.1'
            assert entry.last_login_ip == self.request.user.last_login_ip
            assert entry.version is None
        assert set(checker.history_entries) == set(entries)
        # Still a single failed class: one activity log entry and one failure
        # statsd increment for the class, plus the overall failure increment.
        assert ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).count() == 1
        assert incr_mock.call_count == 2

    def test_history_instance_fields_null_when_nothing_matched(self, incr_mock):
        self.request.user.update(read_dev_agreement=None)
        checker = RestrictionChecker(request=self.request)
        assert not checker.is_submission_allowed()
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == 'DeveloperAgreementRestriction'
        assert history.restriction_instance is None
        assert history.restriction_content_type is None
        assert history.restriction_object_id is None
        assert history.version is None
        assert checker.history_entries == [history]

    def test_history_records_matched_instance_on_auto_approval(self, incr_mock):
        restriction = EmailUserRestriction.objects.create(
            email_pattern=self.request.user.email,
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL,
        )
        upload = FileUpload.objects.create(
            user=self.request.user,
            ip_address='10.0.0.2',
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        checker = RestrictionChecker(upload=upload)
        assert not checker.is_auto_approval_allowed()
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == 'EmailUserRestriction'
        assert history.restriction_instance == restriction
        assert history.version is None
        assert checker.history_entries == [history]

    def test_history_records_matched_instance_on_rating_moderation(self, incr_mock):
        restriction = EmailUserRestriction.objects.create(
            email_pattern=self.request.user.email,
            restriction_type=RESTRICTION_TYPES.RATING_MODERATE,
        )
        checker = RestrictionChecker(request=self.request)
        assert checker.should_moderate_rating()
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == 'EmailUserRestriction'
        assert history.restriction_instance == restriction
        assert history.version is None
        assert checker.history_entries == [history]

    def test_history_entries_empty_on_success(self, incr_mock):
        checker = RestrictionChecker(request=self.request)
        assert checker.is_submission_allowed()
        assert checker.history_entries == []

    def test_history_two_matching_email_restrictions_on_auto_approval(self, incr_mock):
        exact = EmailUserRestriction.objects.create(
            email_pattern=self.request.user.email,
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL,
        )
        wildcard = EmailUserRestriction.objects.create(
            email_pattern='*@%s' % self.request.user.email.rsplit('@', maxsplit=1)[-1],
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL,
        )
        upload = FileUpload.objects.create(
            user=self.request.user,
            ip_address='10.0.0.2',
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        checker = RestrictionChecker(upload=upload)
        assert not checker.is_auto_approval_allowed()
        entries = UserRestrictionHistory.objects.filter(user=self.request.user)
        assert entries.count() == 2
        assert {entry.restriction_instance for entry in entries} == {exact, wildcard}
        for entry in entries:
            assert entry.get_restriction_display() == 'EmailUserRestriction'
            assert entry.version is None
        assert set(checker.history_entries) == set(entries)
        # A single failed class: one activity log entry, carrying both
        # matched instance pks in its details.
        assert ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).count() == 1
        activity = ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).get()
        assert activity.details['restriction'] == 'EmailUserRestriction'
        assert set(activity.details['restriction_ids']) == {exact.pk, wildcard.pk}

    def test_history_instance_fields_null_on_structural_ip_denial(self, incr_mock):
        # An unparseable last_login_ip makes IPNetworkUserRestriction deny
        # auto-approval structurally: the check fails, but no specific
        # restriction instance matched, and a warning is logged.
        self.request.user.update(last_login_ip='not.an.ip.address')
        IPNetworkUserRestriction.objects.create(
            network='10.0.0.0/24',
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL,
        )
        upload = FileUpload.objects.create(
            user=self.request.user,
            ip_address='10.0.0.2',
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        checker = RestrictionChecker(upload=upload)
        with mock.patch('olympia.users.utils.log.warning') as warning_mock:
            assert not checker.is_auto_approval_allowed()
        warning_mock.assert_called_once_with(
            'Failed %s check on %s denied structurally: '
            'input missing or invalid, no instance to record',
            'auto_approval',
            'IPNetworkUserRestriction',
        )
        history = UserRestrictionHistory.objects.get()
        assert history.get_restriction_display() == 'IPNetworkUserRestriction'
        assert history.restriction_instance is None
        assert history.restriction_content_type is None
        assert history.restriction_object_id is None
        assert history.version is None
        assert checker.history_entries == [history]

    def test_error_logged_when_enumeration_finds_nothing(self, incr_mock):
        # A database-backed class denying while enumeration can't reproduce
        # any match should be impossible - the predicates have drifted
        # apart, or the restriction was deleted in between - and is logged
        # as an error.
        checker = RestrictionChecker(request=self.request)
        with ExitStack() as stack:
            for _, cls in UserRestrictionHistory.RESTRICTION_CLASSES_CHOICES:
                stack.enter_context(
                    mock.patch.object(
                        cls,
                        'allow_submission',
                        return_value=cls is not IPNetworkUserRestriction,
                    )
                )
            stack.enter_context(
                mock.patch.object(
                    IPNetworkUserRestriction,
                    'get_matching_restrictions',
                    return_value=[],
                )
            )
            error_mock = stack.enter_context(
                mock.patch('olympia.users.utils.log.error')
            )
            assert not checker.is_submission_allowed()
        error_mock.assert_called_once_with(
            'No matching restrictions found for failed %s check on %s',
            'submission',
            'IPNetworkUserRestriction',
        )
        history = UserRestrictionHistory.objects.get()
        assert history.restriction_instance is None
        assert checker.history_entries == [history]

    def test_no_enumeration_or_recording_for_unauthenticated_failure(self, incr_mock):
        # The full stack never runs the checker unauthenticated (several
        # allow_*() fast paths assume an authenticated user), so patch the
        # fast paths like test_is_submission_allowed_with_mocks() does and
        # prove the guard directly: an unauthenticated failure enumerates
        # nothing and records nothing.
        self.request.user = None
        checker = RestrictionChecker(request=self.request)
        with ExitStack() as stack:
            for _, cls in UserRestrictionHistory.RESTRICTION_CLASSES_CHOICES:
                stack.enter_context(
                    mock.patch.object(
                        cls,
                        'allow_submission',
                        return_value=cls is not IPNetworkUserRestriction,
                    )
                )
            enumeration_mock = stack.enter_context(
                mock.patch.object(IPNetworkUserRestriction, 'get_matching_restrictions')
            )
            assert not checker.is_submission_allowed()
        enumeration_mock.assert_not_called()
        assert checker.failed_restrictions == [IPNetworkUserRestriction]
        assert checker.history_entries == []
        assert not UserRestrictionHistory.objects.exists()
        assert not ActivityLog.objects.filter(action=amo.LOG.RESTRICTED.id).exists()


class TestCheckSuppressedEmailConfirmation(TestCase):
    def setUp(self):
        self.verification = None
        self.user_profile = user_factory()

    def with_verification(self):
        self.verification = SuppressedEmailVerification.objects.create(
            suppressed_email=SuppressedEmail.objects.create(
                email=self.user_profile.email
            )
        )

    def fake_email_response(self, code='', status='Suppressed'):
        return {
            'subject': f'test {code}',
            'status': status,
            'from': 'from',
            'to': 'to',
            'statusDate': '2023-06-26T11:00:00Z',
        }

    def test_fails_missing_settings(self):
        self.with_verification()
        for setting in (
            'SOCKET_LABS_TOKEN',
            'SOCKET_LABS_HOST',
            'SOCKET_LABS_SERVER_ID',
        ):
            with pytest.raises(Exception) as exc:
                setattr(settings, setting, None)
                check_suppressed_email_confirmation(self.verification)
                assert exc.match(f'{setting} is not defined')

    def test_no_verification(self):
        assert not self.user_profile.suppressed_email

        with pytest.raises(AssertionError):
            check_suppressed_email_confirmation(self.verification)

    def test_socket_labs_returns_5xx(self):
        self.with_verification()

        responses.add(
            responses.GET,
            (
                f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/'
                f'reports/recipient-search/'
            ),
            status=500,
        )

        with pytest.raises(Exception):  # noqa: B017
            check_suppressed_email_confirmation(self.verification)

    def test_socket_labs_returns_empty(self):
        self.with_verification()

        responses.add(
            responses.GET,
            (
                f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/'
                f'reports/recipient-search/'
            ),
            status=200,
            body=json.dumps(
                {
                    'data': [],
                    'total': 0,
                }
            ),
            content_type='application/json',
        )

        assert len(check_suppressed_email_confirmation(self.verification)) == 0

    def test_auth_header_present(self):
        self.with_verification()

        responses.add(
            responses.GET,
            (
                f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/'
                f'reports/recipient-search/'
            ),
            status=200,
            body=json.dumps(
                {
                    'data': [],
                    'total': 0,
                }
            ),
            content_type='application/json',
        )

        check_suppressed_email_confirmation(self.verification)

        assert (
            settings.SOCKET_LABS_TOKEN
            in responses.calls[0].request.headers['authorization']
        )

    @time_machine.travel('2023-06-26 11:00', tick=False)
    def test_format_date_params(self):
        self.with_verification()

        responses.add(
            responses.GET,
            (
                f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/'
                f'reports/recipient-search/'
            ),
            status=200,
            body=json.dumps(
                {
                    'data': [],
                    'total': 0,
                }
            ),
            content_type='application/json',
        )

        check_suppressed_email_confirmation(self.verification)

        parsed_url = urlparse(responses.calls[0].request.url)
        search_params = parse_qs(parsed_url.query)

        assert search_params['startDate'][0] == '2023-06-25'
        assert search_params['endDate'][0] == '2023-06-27'

    def test_pagination(self):
        self.with_verification()

        response_size = 5

        body = [self.fake_email_response() for _ in range(response_size)]

        url = (
            f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/'
            f'reports/recipient-search/'
        )

        responses.add(
            responses.GET,
            url,
            status=200,
            body=json.dumps(
                {
                    'data': body,
                    'total': response_size + 1,
                }
            ),
            content_type='application/json',
        )
        code_snippet = str(self.verification.confirmation_code)[-5:]
        responses.add(
            responses.GET,
            url,
            status=200,
            body=json.dumps(
                {
                    'data': [self.fake_email_response(code_snippet)],
                    'total': response_size + 1,
                }
            ),
            content_type='application/json',
        )

        check_suppressed_email_confirmation(self.verification, response_size)

        assert len(responses.calls) == 2

    def test_found_email(self):
        self.with_verification()

        response_size = 5

        body = [self.fake_email_response() for _ in range(response_size)]

        url = (
            f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/'
            f'reports/recipient-search/'
        )

        responses.add(
            responses.GET,
            url,
            status=200,
            body=json.dumps(
                {
                    'data': body,
                    'total': response_size + 1,
                }
            ),
            content_type='application/json',
        )
        code_snippet = str(self.verification.confirmation_code)[-5:]
        responses.add(
            responses.GET,
            url,
            status=200,
            body=json.dumps(
                {
                    'data': [self.fake_email_response(code_snippet, 'Delivered')],
                    'total': response_size + 1,
                }
            ),
            content_type='application/json',
        )

        check_suppressed_email_confirmation(self.verification, response_size)

        assert (
            self.verification.reload().status
            == SuppressedEmailVerification.STATUS_CHOICES.DELIVERED
        )

    def test_verify_response_data(self):
        self.with_verification()

        response_size = 1

        url = (
            f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/'
            f'reports/recipient-search/'
        )

        code_snippet = str(self.verification.confirmation_code)[-5:]
        responses.add(
            responses.GET,
            url,
            status=200,
            body=json.dumps(
                {
                    'data': [self.fake_email_response(code_snippet, 'Delivered')],
                    'total': response_size,
                }
            ),
            content_type='application/json',
        )

        result = check_suppressed_email_confirmation(self.verification, response_size)

        assert len(result) == 1
        assert result[0]['subject'] == f'test {code_snippet}'
        assert result[0]['status'] == 'Delivered'
        assert result[0]['from'] == 'from'
        assert result[0]['to'] == 'to'
        assert result[0]['statusDate'] == '2023-06-26T11:00:00Z'

    def test_not_delivered_status(self):
        self.with_verification()

        response_size = 3

        url = (
            f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/'
            f'reports/recipient-search/'
        )

        code_snippet = str(self.verification.confirmation_code)[-5:]
        responses.add(
            responses.GET,
            url,
            status=200,
            body=json.dumps(
                {
                    'data': [
                        self.fake_email_response(code_snippet, 'InvalidStatus'),
                        self.fake_email_response('', 'Delivered'),
                        self.fake_email_response('', 'Suppressed'),
                    ],
                    'total': 3,
                }
            ),
            content_type='application/json',
        )

        result = check_suppressed_email_confirmation(self.verification, response_size)

        assert len(result) == response_size

        assert result[0]['status'] == 'InvalidStatus'

    def test_response_does_not_contain_suppressed_email(self):
        self.with_verification()

        response_size = 5

        body = [self.fake_email_response() for _ in range(response_size)]

        url = (
            f'{settings.SOCKET_LABS_HOST}servers/{settings.SOCKET_LABS_SERVER_ID}/'
            f'reports/recipient-search/'
        )

        responses.add(
            responses.GET,
            url,
            status=200,
            body=json.dumps(
                {
                    'data': body,
                    'total': response_size,
                }
            ),
            content_type='application/json',
        )

        result = check_suppressed_email_confirmation(self.verification, response_size)

        assert len(result) == response_size
