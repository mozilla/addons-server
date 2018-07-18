from datetime import datetime, timedelta

from django import http
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

import mock
import pytest

from olympia import amo
from olympia.amo import decorators
from olympia.amo.tests import BaseTestCase, TestCase, fxa_login_link
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
    assert response.content == '{"x": 1}'
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
    assert response.content == '{"msg": "error"}'
    assert response['Content-Type'] == 'application/json'


def test_json_view_status():
    def func(request):
        return {'x': 1}

    response = decorators.json_view(func, status_code=202)(mock.Mock())
    assert response.status_code == 202


def test_json_view_response_status():
    response = decorators.json_response({'msg': 'error'}, status_code=202)
    assert response.content == '{"msg": "error"}'
    assert response['Content-Type'] == 'application/json'
    assert response.status_code == 202


class TestLoginRequired(BaseTestCase):
    def setUp(self):
        super(TestLoginRequired, self).setUp()
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
        assert response['Location'] == fxa_login_link(
            request=self.request, to='/path'
        )

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
        super(TestPermissionRequired, self).setUp()
        self.f = mock.Mock()
        self.f.__name__ = 'function'
        self.request = mock.Mock()

    @mock.patch('olympia.access.acl.action_allowed')
    def test_permission_not_allowed(self, action_allowed):
        action_allowed.return_value = False
        func = decorators.permission_required(self.empty_permission)(self.f)
        with self.assertRaises(PermissionDenied):
            func(self.request)

    @mock.patch('olympia.access.acl.action_allowed')
    def test_permission_allowed(self, action_allowed):
        action_allowed.return_value = True
        func = decorators.permission_required(self.empty_permission)(self.f)
        func(self.request)
        assert self.f.called

    @mock.patch('olympia.access.acl.action_allowed')
    def test_permission_allowed_correctly(self, action_allowed):
        func = decorators.permission_required(amo.permissions.ANY_ADMIN)(
            self.f
        )
        func(self.request)
        action_allowed.assert_called_with(
            self.request, amo.permissions.AclPermission('Admin', '%')
        )
