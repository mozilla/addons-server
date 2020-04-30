from django.test import RequestFactory

from olympia.amo.tests import TestCase, user_factory
from olympia.devhub.permissions import IsSubmissionAllowedFor
from olympia.users.models import (
    DisposableEmailDomainRestriction, EmailUserRestriction,
    IPNetworkUserRestriction)


class TestIsSubmissionAllowedFor(TestCase):
    def setUp(self):
        self.permission = IsSubmissionAllowedFor()
        self.view = object()
        self.request = RequestFactory().post('/')
        self.request.is_api = False
        self.request.user = user_factory(
            email='test@example.com', read_dev_agreement=self.days_ago(0))
        self.request.user.update(last_login_ip='192.168.1.1')

    def test_has_permission_no_restrictions(self):
        assert self.permission.has_permission(self.request, self.view)

    def test_has_object_permission_no_restrictions(self):
        assert self.permission.has_object_permission(
            self.request, self.view, object())

    def test_has_permission_user_has_not_read_agreement(self):
        self.request.user.update(read_dev_agreement=None)
        assert not self.permission.has_permission(self.request, self.view)
        assert self.permission.message == (
            'Before starting, please read and accept our Firefox Add-on '
            'Distribution Agreement as well as our Review Policies and Rules. '
            'The Firefox Add-on Distribution Agreement also links to our '
            'Privacy Notice which explains how we handle your information.')

    def test_has_permission_user_has_not_read_agreement_when_using_API(self):
        self.request.is_api = True
        self.request.user.update(read_dev_agreement=None)
        assert not self.permission.has_permission(self.request, self.view)
        assert self.permission.message == (
            'Please read and accept our Firefox Add-on Distribution Agreement '
            'as well as our Review Policies and Rules by visiting '
            'http://testserver/en-US/developers/addon/api/key/'
        )

    def test_has_permission_disposable_email(self):
        DisposableEmailDomainRestriction.objects.create(domain='example.com')
        assert not self.permission.has_permission(self.request, self.view)
        assert self.permission.message == (
            'The email address used for your account is not '
            'allowed for add-on submission.')

    def test_has_permission_user_ip_restricted(self):
        self.request.META['REMOTE_ADDR'] = '127.0.0.1'
        IPNetworkUserRestriction.objects.create(network='127.0.0.1/32')
        assert not self.permission.has_permission(self.request, self.view)
        assert self.permission.message == (
            'Multiple add-ons violating our policies have been submitted '
            'from your location. The IP address has been blocked.')

    def test_has_permission_user_email_restricted(self):
        EmailUserRestriction.objects.create(email_pattern='test@example.com')
        assert not self.permission.has_permission(self.request, self.view)
        assert self.permission.message == (
            'The email address used for your account is not '
            'allowed for add-on submission.')

    def test_has_permission_both_user_ip_and_email_restricted(self):
        self.request.META['REMOTE_ADDR'] = '127.0.0.1'
        IPNetworkUserRestriction.objects.create(network='127.0.0.1/32')
        EmailUserRestriction.objects.create(email_pattern='test@example.com')
        assert not self.permission.has_permission(self.request, self.view)
        assert self.permission.message == (
            'The email address used for your account is not '
            'allowed for add-on submission.')
