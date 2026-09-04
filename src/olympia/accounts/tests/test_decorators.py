import time
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test.client import RequestFactory

from waffle.testutils import override_switch

from olympia.accounts.decorators import two_factor_auth_required
from olympia.accounts.utils import redirect_for_login_with_2fa_enforced
from olympia.amo.tests import TestCase, user_factory


class TestTwoFactorAuthRequired(TestCase):
    def setUp(self):
        self.user = user_factory()
        self.f = mock.Mock()
        self.f.__name__ = 'function'
        self.f.return_value = 'FakeResponse'
        self.request = RequestFactory().get('/')
        self.request.session = {}
        self.request.user = AnonymousUser()

    def test_has_two_factor_auth(self):
        self.request.session['has_two_factor_authentication'] = True
        func = two_factor_auth_required(self.f)
        response = func(self.request)
        assert self.f.call_count == 1
        assert response == 'FakeResponse'

    def test_does_not_have_two_factor_auth_yet(self):
        self.request.user = self.user
        func = two_factor_auth_required(self.f)
        response = func(self.request)
        assert self.f.call_count == 0
        expected_redirect_url = redirect_for_login_with_2fa_enforced(
            self.request, login_hint=self.user.email
        )['location']
        self.assert3xx(response, expected_redirect_url)

    def test_does_not_have_two_factor_auth_yet_anonymous(self):
        func = two_factor_auth_required(self.f)
        response = func(self.request)
        assert self.f.call_count == 0
        expected_redirect_url = redirect_for_login_with_2fa_enforced(self.request)[
            'location'
        ]
        self.assert3xx(response, expected_redirect_url)

    @override_switch('2fa-reprompt', active=True)
    def test_does_not_have_two_factor_auth_ignore_reprompt(self):
        self.request.user = self.user
        func = two_factor_auth_required(self.f)
        response = func(self.request)
        assert self.f.call_count == 0
        expected_redirect_url = redirect_for_login_with_2fa_enforced(
            self.request, login_hint=self.user.email
        )['location']
        self.assert3xx(response, expected_redirect_url)

    @override_switch('2fa-reprompt', active=True)
    def test_has_two_factor_auth_should_be_reprompted_no_auth_at(self):
        self.request.session['has_two_factor_authentication'] = True
        self.request.user = self.user
        func = two_factor_auth_required(self.f)
        response = func(self.request)
        assert self.f.call_count == 0
        expected_redirect_url = redirect_for_login_with_2fa_enforced(self.request)[
            'location'
        ]
        self.assert3xx(response, expected_redirect_url)

    @override_switch('2fa-reprompt', active=True)
    def test_has_two_factor_auth_should_be_reprompted_old_auth_at(self):
        self.request.session['has_two_factor_authentication'] = True
        self.request.session['fxa_auth_at'] = int(
            time.time() - settings.FXA_MAX_AUTH_TIME_BEFORE_MFA_REPROMPT - 10
        )
        self.request.user = self.user
        func = two_factor_auth_required(self.f)
        response = func(self.request)
        assert self.f.call_count == 0
        expected_redirect_url = redirect_for_login_with_2fa_enforced(self.request)[
            'location'
        ]
        self.assert3xx(response, expected_redirect_url)

    @override_switch('2fa-reprompt', active=True)
    def test_has_two_factor_auth_should_not_be_reprompted(self):
        self.request.session['has_two_factor_authentication'] = True
        self.request.session['fxa_auth_at'] = int(
            time.time() - settings.FXA_MAX_AUTH_TIME_BEFORE_MFA_REPROMPT + 10
        )
        func = two_factor_auth_required(self.f)
        response = func(self.request)
        assert self.f.call_count == 1
        assert response == 'FakeResponse'
