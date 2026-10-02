import time
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test.client import RequestFactory
from django.urls import reverse

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
    def test_has_two_factor_auth_should_be_reprompted_cant_post_data_anonymous(self):
        # If somehow the user is anonymous despite having correct session data,
        # don't store post data for replaying.
        self.request = RequestFactory().post(
            '/somewhere/important', {'foo': 'baré', 'a': ['1', '2'], 'b': 'c'}
        )
        self.request.user = AnonymousUser()
        self.request.session = {}
        self.request.session['has_two_factor_authentication'] = True
        self.request.session['fxa_auth_at'] = int(
            time.time() - settings.FXA_MAX_AUTH_TIME_BEFORE_MFA_REPROMPT - 10
        )
        func = two_factor_auth_required(self.f)
        response = func(self.request)
        assert self.f.call_count == 0
        assert '_post_data_after_2fa_reprompt' not in self.request.session
        # Redirect normally (not to the special post restore endpoint)
        expected_redirect_url = redirect_for_login_with_2fa_enforced(self.request)[
            'location'
        ]
        self.assert3xx(response, expected_redirect_url)

    @override_switch('2fa-reprompt', active=True)
    @mock.patch('olympia.accounts.decorators.TimestampSigner.sign')
    def test_has_two_factor_auth_should_be_reprompted_with_post_data(self, sign_mock):
        sign_mock.return_value = expected_signature = 'fake_signature'
        self.request = RequestFactory().post(
            '/somewhere/important', {'foo': 'baré', 'a': ['1', '2'], 'b': 'c'}
        )
        self.request.user = self.user
        self.request.session = {}
        self.request.session['has_two_factor_authentication'] = True
        self.request.session['fxa_auth_at'] = int(
            time.time() - settings.FXA_MAX_AUTH_TIME_BEFORE_MFA_REPROMPT - 10
        )
        assert '_post_data_after_2fa_reprompt' not in self.request.session
        func = two_factor_auth_required(self.f)
        response = func(self.request)
        assert self.f.call_count == 0
        session = self.request.session
        assert '_post_data_after_2fa_reprompt' in session
        assert session['_post_data_after_2fa_reprompt']['url'] == '/somewhere/important'
        assert (
            session['_post_data_after_2fa_reprompt']['data']
            == self.request.POST.urlencode()
        )
        expected_next_path = (
            f'{reverse("auth:accounts.restore-post")}?s={expected_signature}'
        )
        expected_redirect_url = redirect_for_login_with_2fa_enforced(
            self.request, next_path=expected_next_path
        )['location']
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
