from datetime import datetime, timedelta
from unittest import mock

from django import http
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.utils.encoding import force_str

import pytest

from rest_framework import exceptions as drf_exceptions

from olympia import amo
from olympia.amo import decorators
from olympia.amo.tests import TestCase, fxa_login_link
from olympia.api.authentication import JWTKeyAuthentication, SessionIDAuthentication
from olympia.users.models import UserProfile


pytestmark = pytest.mark.django_db


def test_post_required():
    def func(request):
        return mock.sentinel.response

    g = decorators.post_required(func)

    request = mock.Mock()
    request.method = 'GET'
    assert isinstance(g(request), http.HttpResponseNotAllowed)

    request.method = 'POST'
    assert g(request) == mock.sentinel.response


def test_json_view():
    """Turns a Python object into a response."""

    def func(request):
        return {'x': 1}

    response = decorators.json_view(func)(mock.Mock())
    assert isinstance(response, http.HttpResponse)
    assert force_str(response.content) == '{"x": 1}'
    assert response['Content-Type'] == 'application/json'
    assert response.status_code == 200


def test_json_view_normal_response():
    """Normal responses get passed through."""
    expected = http.HttpResponseForbidden()

    def func(request):
        return expected

    response = decorators.json_view(func)(mock.Mock())
    assert expected is response
    assert response['Content-Type'] == 'text/html; charset=utf-8'


def test_json_view_error():
    """json_view.error returns 400 responses."""
    response = decorators.json_view.error({'msg': 'error'})
    assert isinstance(response, http.HttpResponseBadRequest)
    assert force_str(response.content) == '{"msg": "error"}'
    assert response['Content-Type'] == 'application/json'


def test_json_view_status():
    def func(request):
        return {'x': 1}

    response = decorators.json_view(func, status_code=202)(mock.Mock())
    assert response.status_code == 202


def test_json_view_response_status():
    response = decorators.json_response({'msg': 'error'}, status_code=202)
    assert force_str(response.content) == '{"msg": "error"}'
    assert response['Content-Type'] == 'application/json'
    assert response.status_code == 202


class TestLoginRequired(TestCase):
    def setUp(self):
        super().setUp()
        self.f = mock.Mock()
        self.f.__name__ = 'function'
        self.request = RequestFactory().get('/path')
        self.request.user = AnonymousUser()
        self.request.session = {}

    def test_normal(self):
        func = decorators.login_required(self.f)
        response = func(self.request)
        assert not self.f.called
        assert response.status_code == 302
        assert response['Location'] == fxa_login_link(request=self.request, to='/path')

    def test_no_redirect(self):
        func = decorators.login_required(self.f, redirect=False)
        response = func(self.request)
        assert not self.f.called
        assert response.status_code == 401

    def test_decorator_syntax(self):
        # @login_required(redirect=False)
        func = decorators.login_required(redirect=False)(self.f)
        response = func(self.request)
        assert not self.f.called
        assert response.status_code == 401

    def test_no_redirect_success(self):
        func = decorators.login_required(redirect=False)(self.f)
        self.request.user = UserProfile()
        func(self.request)
        assert self.f.called


class TestSetModifiedOn(TestCase):
    fixtures = ['base/users']

    @decorators.set_modified_on
    def some_method(self, worked):
        return worked

    def test_set_modified_on(self):
        user = UserProfile.objects.latest('pk')
        self.some_method(True, set_modified_on=user.serializable_reference())
        assert UserProfile.objects.get(pk=user.pk).modified.date() == (
            datetime.today().date()
        )

    def test_not_set_modified_on(self):
        yesterday = datetime.today() - timedelta(days=1)
        qs = UserProfile.objects.all()
        qs.update(modified=yesterday)
        user = qs.latest('pk')
        self.some_method(False, set_modified_on=user.serializable_reference())
        date = UserProfile.objects.get(pk=user.pk).modified.date()
        assert date < datetime.today().date()


class TestPermissionRequired(TestCase):
    empty_permission = amo.permissions.NONE

    def setUp(self):
        super().setUp()
        self.f = mock.Mock()
        self.f.__name__ = 'function'
        self.request = mock.Mock()

    @mock.patch('olympia.access.acl.action_allowed_for')
    def test_permission_not_allowed(self, action_allowed_for):
        action_allowed_for.return_value = False
        func = decorators.permission_required(self.empty_permission)(self.f)
        with self.assertRaises(PermissionDenied):
            func(self.request)

    @mock.patch('olympia.access.acl.action_allowed_for')
    def test_permission_allowed(self, action_allowed_for):
        action_allowed_for.return_value = True
        func = decorators.permission_required(self.empty_permission)(self.f)
        func(self.request)
        assert self.f.called

    @mock.patch('olympia.access.acl.action_allowed_for')
    def test_permission_allowed_correctly(self, action_allowed_for):
        func = decorators.permission_required(amo.permissions.ANY_ADMIN)(self.f)
        func(self.request)
        action_allowed_for.assert_called_with(
            self.request.user, amo.permissions.AclPermission('Admin', '%')
        )


class TestApiAuthentication(TestCase):
    def setUp(self):
        super().setUp()
        self.f = mock.Mock()
        self.f.__name__ = 'function'
        self.request = mock.Mock()
        self.request.user = mock.Mock()
        self.request.user.is_anonymous = True
        self.function = decorators.api_authentication(self.f)
        self.session_id_auth_mock = self.patch(
            'olympia.api.authentication.SessionIDAuthentication.authenticate'
        )
        self.session_id_auth_mock.return_value = None
        self.jwt_key_auth_mock = self.patch(
            'olympia.api.authentication.JWTKeyAuthentication.authenticate'
        )
        self.jwt_key_auth_mock.return_value = None

    @mock.patch('olympia.amo.decorators.get_authorization_header')
    def test_already_authd(self, get_authorization_header_mock):
        self.request.user.is_anonymous = False
        self.function(self.request, 123)
        self.f.assert_called_with(self.request, 123)
        get_authorization_header_mock.assert_not_called()

    def test_no_api_auth_header(self):
        self.request.META = {}
        self.function(self.request, 123)
        self.f.assert_called_with(self.request, 123)
        self.session_id_auth_mock.assert_not_called()
        self.jwt_key_auth_mock.assert_not_called()

    def test_no_compatible_auth_header(self):
        self.request.META = {'HTTP_AUTHORIZATION': 'SomeOtherThing'}
        self.function(self.request, 123)
        self.f.assert_called_with(self.request, 123)
        self.session_id_auth_mock.assert_called()
        self.jwt_key_auth_mock.assert_called()

    def _test_auth_success(self, authenticate_mock, AuthClass):
        api_user = mock.Mock()
        self.request.META = {
            'HTTP_AUTHORIZATION': AuthClass().authenticate_header(self.request)
        }
        authenticate_mock.return_value = (api_user, None)
        self.function(self.request, 123)
        self.f.assert_called_with(self.request, 123)
        assert self.request.user == api_user

    def test_auth_success_session_id(self):
        self._test_auth_success(self.session_id_auth_mock, SessionIDAuthentication)
        # Once we have a passing auth the second auth class shouldn't be attempted
        self.jwt_key_auth_mock.assert_not_called()

    def test_auth_success_jwt(self):
        self._test_auth_success(self.jwt_key_auth_mock, JWTKeyAuthentication)
        # SessionID auth should have been tried first and ignored
        self.session_id_auth_mock.assert_called()

    def _test_auth_fail(self, authenticate_mock, AuthClass):
        api_user = mock.Mock()
        self.request.META = {
            'HTTP_AUTHORIZATION': AuthClass().authenticate_header(self.request)
        }
        authenticate_mock.side_effect = drf_exceptions.AuthenticationFailed
        result = self.function(self.request, 123)
        self.f.assert_not_called()
        assert self.request.user != api_user
        assert result.status_code == 401
        assert result.data == {'detail': 'Incorrect authentication credentials.'}

    def test_auth_fail_session_id(self):
        self._test_auth_fail(self.session_id_auth_mock, SessionIDAuthentication)
        # Once we have a failing auth the second auth class shouldn't be attempted
        self.jwt_key_auth_mock.assert_not_called()

    def test_auth_fail_jwt(self):
        self._test_auth_fail(self.jwt_key_auth_mock, JWTKeyAuthentication)
        # SessionID auth should have been tried first and ignored
        self.session_id_auth_mock.assert_called()
