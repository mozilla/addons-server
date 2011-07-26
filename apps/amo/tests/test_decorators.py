from datetime import datetime
from django import http

import mock
from nose.tools import eq_
import test_utils

from amo import decorators
from amo.urlresolvers import reverse

from users.models import UserProfile


def test_post_required():
    f = lambda r: mock.sentinel.response
    g = decorators.post_required(f)

    request = mock.Mock()
    request.method = 'GET'
    assert isinstance(g(request), http.HttpResponseNotAllowed)

    request.method = 'POST'
    eq_(g(request), mock.sentinel.response)


def test_json_view():
    """Turns a Python object into a response."""
    f = lambda r: {'x': 1}
    response = decorators.json_view(f)(mock.Mock())
    assert isinstance(response, http.HttpResponse)
    eq_(response.content, '{"x": 1}')
    eq_(response['Content-Type'], 'application/json')


def test_json_view_normal_response():
    """Normal responses get passed through."""
    expected = http.HttpResponseForbidden()
    f = lambda r: expected
    response = decorators.json_view(f)(mock.Mock())
    assert expected is response
    eq_(response['Content-Type'], 'text/html; charset=utf-8')


def test_json_view_error():
    """json_view.error returns 400 responses."""
    response = decorators.json_view.error({'msg': 'error'})
    assert isinstance(response, http.HttpResponseBadRequest)
    eq_(response.content, '{"msg": "error"}')
    eq_(response['Content-Type'], 'application/json')


class TestLoginRequired(object):

    def setUp(self):
        self.f = mock.Mock()
        self.f.__name__ = 'function'
        self.request = mock.Mock()
        self.request.user.is_authenticated.return_value = False
        self.request.get_full_path.return_value = 'path'

    def test_normal(self):
        func = decorators.login_required(self.f)
        response = func(self.request)
        assert not self.f.called
        eq_(response.status_code, 302)
        eq_(response['Location'],
            '%s?to=%s' % (reverse('users.login'), 'path'))

    def test_no_redirect(self):
        func = decorators.login_required(self.f, redirect=False)
        response = func(self.request)
        assert not self.f.called
        eq_(response.status_code, 401)

    def test_decorator_syntax(self):
        # @login_required(redirect=False)
        func = decorators.login_required(redirect=False)(self.f)
        response = func(self.request)
        assert not self.f.called
        eq_(response.status_code, 401)

    def test_no_redirect_success(self):
        func = decorators.login_required(redirect=False)(self.f)
        self.request.user.is_authenticated.return_value = True
        func(self.request)
        assert self.f.called


class TestSetModifiedOn(test_utils.TestCase):
    fixtures = ['base/users']

    @decorators.set_modified_on
    def some_method(self, worked):
        return worked

    def test_set_modified_on(self):
        users = list(UserProfile.objects.all()[:3])
        self.some_method(True, set_modified_on=users)
        for user in users:
            eq_(UserProfile.objects.get(pk=user.pk).modified.date(),
                datetime.today().date())

    def test_not_set_modified_on(self):
        users = list(UserProfile.objects.all()[:3])
        self.some_method(False, set_modified_on=users)
        for user in users:
            date = UserProfile.objects.get(pk=user.pk).modified.date()
            assert date < datetime.today().date()


class TestPermissionRequired(test_utils.TestCase):

    def setUp(self):
        self.f = mock.Mock()
        self.f.__name__ = 'function'
        self.request = mock.Mock()

    @mock.patch('access.acl.action_allowed')
    def test_permission_not_allowed(self, action_allowed):
        action_allowed.return_value = False
        func = decorators.permission_required('', '')(self.f)
        eq_(func(self.request).status_code, 403)

    @mock.patch('access.acl.action_allowed')
    def test_permission_allowed(self, action_allowed):
        action_allowed.return_value = True
        func = decorators.permission_required('', '')(self.f)
        func(self.request)
        assert self.f.called

    @mock.patch('access.acl.action_allowed')
    def test_permission_allowed_correctly(self, action_allowed):
        func = decorators.permission_required('Admin', '%')(self.f)
        func(self.request)
        action_allowed.assert_called_with(self.request, 'Admin', '%')
