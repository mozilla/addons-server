from django.contrib.auth.models import AnonymousUser, User

from rest_framework.permissions import AllowAny, BasePermission
from mock import Mock
from nose.tools import eq_, ok_
from test_utils import RequestFactory

from amo.tests import app_factory, TestCase
from users.models import UserProfile

from mkt.api.authorization import (AllowAppOwner, AllowNone, AllowOwner,
                                   AllowRelatedAppOwner, AllowSelf,
                                   AnonymousReadOnlyAuthorization, AnyOf,
                                   ByHttpMethod, flag, GroupPermission,
                                   PermissionAuthorization, switch)
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp

from .test_authentication import OwnerAuthorization


class TestAnonymousReadOnlyAuthorization(TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.get = RequestFactory().get('/')
        self.post = RequestFactory().post('/')
        self.auth = AnonymousReadOnlyAuthorization()
        self.anon = AnonymousUser()
        self.user = User.objects.get(pk=2519)

    def test_get_anonymous(self):
        self.get.user = self.anon
        eq_(self.auth.is_authorized(self.get), True)

    def test_get_authenticated(self):
        self.get.user = self.user
        eq_(self.auth.is_authorized(self.get), True)

    def test_post_anonymous(self):
        self.post.user = self.anon
        eq_(self.auth.is_authorized(self.post), False)

    def test_post_authenticated(self):
        self.post.user = self.user
        eq_(self.auth.is_authorized(self.post), True)

    def test_with_authorizer(self):

        class LockedOut:
            def is_authorized(self, request, object=None):
                return False

        self.auth = AnonymousReadOnlyAuthorization(
                                authorizer=LockedOut())
        self.post.user = self.user
        eq_(self.auth.is_authorized(self.post), False)


class TestPermissionAuthorization(OwnerAuthorization):

    def setUp(self):
        super(TestPermissionAuthorization, self).setUp()
        self.auth = PermissionAuthorization('Drinkers', 'Beer')
        self.app = app_factory()

    def test_has_role(self):
        self.grant_permission(self.profile, 'Drinkers:Beer')
        ok_(self.auth.is_authorized(self.request(self.profile), self.app))

    def test_not_has_role(self):
        self.grant_permission(self.profile, 'Drinkers:Scotch')
        ok_(not self.auth.is_authorized(self.request(self.profile), self.app))


class TestWaffle(TestCase):

    def setUp(self):
        super(TestWaffle, self).setUp()
        self.request = RequestFactory().get('/')

    def test_waffle_flag(self):
        self.create_flag('foo')
        ok_(flag('foo')().has_permission(self.request, ''))

    def test_not_waffle_flag(self):
        ok_(not flag('foo')().has_permission(self.request, ''))

    def test_waffle_switch(self):
        self.create_switch('foo')
        ok_(switch('foo')().has_permission(self.request, ''))

    def test_not_switch_flag(self):
        ok_(not switch('foo')().has_permission(self.request, ''))


class TestAllowSelfAuthorization(TestCase):
    fixtures = fixture('user_2519', 'user_999')

    def setUp(self):
        self.permission = AllowSelf()
        self.anonymous = AnonymousUser()
        self.user = User.objects.get(pk=2519)
        self.request = RequestFactory().get('/')
        self.request.user = self.anonymous
        self.request.amo_user = None

    def test_has_permission_anonymous(self):
        eq_(self.permission.has_permission(self.request, 'myview'), False)

    def test_has_permission_user(self):
        self.request.user = self.user
        self.request.amo_user = self.request.user.get_profile()
        eq_(self.permission.has_permission(self.request, 'myview'), True)

    def test_has_object_permission_anonymous(self):
        eq_(self.permission.has_object_permission(
            self.request, 'myview', self.user), False)

    def test_has_object_permission_user(self):
        self.request.user = self.user
        self.request.amo_user = self.request.user.get_profile()
        obj = self.user
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            True)

    def test_has_object_permission_different_user(self):
        self.request.user = User.objects.get(pk=999)
        self.request.amo_user = self.request.user.get_profile()
        obj = self.user
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            False)


class TestAllowOwner(TestCase):
    fixtures = fixture('user_2519', 'user_999')

    def setUp(self):
        self.permission = AllowOwner()
        self.anonymous = AnonymousUser()
        self.user = User.objects.get(pk=2519)
        self.request = RequestFactory().get('/')
        self.request.user = self.anonymous
        self.request.amo_user = None

    def test_has_permission_anonymous(self):
        eq_(self.permission.has_permission(self.request, 'myview'), False)

    def test_has_permission_user(self):
        self.request.user = self.user
        self.request.amo_user = self.request.user.get_profile()
        eq_(self.permission.has_permission(self.request, 'myview'), True)

    def test_has_object_permission_user(self):
        self.request.user = self.user
        self.request.amo_user = self.request.user.get_profile()
        obj = Mock()
        obj.user = self.user
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            True)

    def test_has_object_permission_different_user(self):
        self.request.user = User.objects.get(pk=999)
        self.request.amo_user = self.request.user.get_profile()
        obj = Mock()
        obj.user = self.user
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            False)


class PartialFailPermission(BasePermission):
    def has_object_permission(self, request, view, obj):
        return False


class FailPartialPermission(BasePermission):
    def has_permission(self, request, view):
        return False


class TestAnyOf(TestCase):
    def test_has_permission(self):
        request = RequestFactory().get('/')
        ok_(AnyOf(AllowNone, AllowAny)().has_permission(
            request, 'myview'))
        ok_(AnyOf(AllowAny, AllowNone)().has_permission(
            request, 'myview'))

    def test_has_permission_fail(self):
        request = RequestFactory().get('/')
        ok_(not AnyOf(AllowNone, AllowNone)().has_permission(
            request, 'myview'))

    def test_has_object_permission(self):
        request = RequestFactory().get('/')
        ok_(AnyOf(AllowNone, AllowAny
                  )().has_object_permission(request, 'myview', None))
        ok_(AnyOf(AllowAny, AllowNone
                  )().has_object_permission(request, 'myview', None))

    def test_has_object_permission_fail(self):
        request = RequestFactory().get('/')
        ok_(not AnyOf(AllowNone, AllowNone
                      )().has_object_permission(request, 'myview', None))

    def test_has_object_permission_partial_fail(self):
        request = RequestFactory().get('/')
        ok_(not AnyOf(FailPartialPermission, PartialFailPermission
                      )().has_object_permission(request, 'myview', None))


class TestAllowNone(TestCase):
    def setUp(self):
        self.permission = AllowNone()
        self.anonymous = AnonymousUser()
        self.user = User()
        self.request = RequestFactory().get('/')
        self.request.user = self.anonymous
        self.request.amo_user = None

    def test_has_permission_anonymous(self):
        eq_(self.permission.has_permission(self.request, 'myview'), False)

    def test_has_permission_user(self):
        self.request.user = Mock()
        self.request_amo_user = Mock()
        eq_(self.permission.has_permission(self.request, 'myview'), False)

    def test_has_object_permission_anonymous(self):
        obj = Mock()
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            False)

    def test_has_object_permission_user(self):
        self.request.user = Mock()
        self.request_amo_user = Mock()
        obj = Mock()
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            False)


class TestAllowAppOwner(TestCase):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.permission = AllowAppOwner()
        self.anonymous = AnonymousUser()
        self.owner = self.app.authors.all()[0]
        self.request = RequestFactory().get('/')
        self.request.user = self.anonymous
        self.request.amo_user = None

    def test_has_permission_anonymous(self):
        eq_(self.permission.has_permission(self.request, 'myview'), False)

    def test_has_permission_user(self):
        self.request.user = self.owner.user
        self.request.amo_user = self.owner
        eq_(self.permission.has_permission(self.request, 'myview'), True)

    def test_has_object_permission_user(self):
        self.request.user = self.owner.user
        self.request.amo_user = self.owner
        obj = self.app
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            True)

    def test_has_object_permission_different_user(self):
        self.request.user = User.objects.get(pk=2519)
        self.request.amo_user = self.request.user.get_profile()
        obj = self.app
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            False)

    def test_has_object_permission_anonymous(self):
        obj = self.app
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            False)


class TestAllowRelatedAppOwner(TestCase):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.permission = AllowRelatedAppOwner()
        self.anonymous = AnonymousUser()
        self.owner = self.app.authors.all()[0]
        self.request = RequestFactory().get('/')
        self.request.user = self.anonymous
        self.request.amo_user = None

    def test_has_permission_anonymous(self):
        eq_(self.permission.has_permission(self.request, 'myview'), False)

    def test_has_permission_user(self):
        self.request.user = self.owner.user
        self.request.amo_user = self.owner
        eq_(self.permission.has_permission(self.request, 'myview'), True)

    def test_has_object_permission_user(self):
        self.request.user = self.owner.user
        self.request.amo_user = self.owner
        obj = Mock()
        obj.addon = self.app
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            True)

    def test_has_object_permission_different_user(self):
        self.request.user = User.objects.get(pk=2519)
        self.request.amo_user = self.request.user.get_profile()
        obj = Mock()
        obj.addon = self.app
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            False)


class TestGroupPermission(TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.permission = GroupPermission('Drinkers', 'Beer')
        self.obj = Mock()
        self.profile = UserProfile.objects.get(pk=2519)
        self.anonymous = AnonymousUser()
        self.request = RequestFactory().get('/')
        self.request.user = self.anonymous

    def test_has_permission_user_without(self):
        self.request.user = self.profile.user
        self.request.amo_user = self.profile
        self.request.groups = self.profile.groups.all()
        self.grant_permission(self.profile, 'Drinkers:Scotch')
        eq_(self.permission.has_permission(self.request, 'myview'), False)

    def test_has_permission_user_with(self):
        self.request.user = self.profile.user
        self.request.amo_user = self.profile
        self.request.groups = self.profile.groups.all()
        self.grant_permission(self.profile, 'Drinkers:Beer')
        eq_(self.permission.has_permission(self.request, 'myview'), True)

    def test_has_permission_anonymous(self):
        eq_(self.permission.has_permission(self.request, 'myview'), False)

    def test_has_object_permission_user_without(self):
        self.request.user = self.profile.user
        self.request.amo_user = self.profile
        self.request.groups = self.profile.groups.all()
        self.grant_permission(self.profile, 'Drinkers:Scotch')
        obj = Mock()
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            False)

    def test_has_object_permission_user_with(self):
        self.request.user = self.profile.user
        self.request.amo_user = self.profile
        self.request.groups = self.profile.groups.all()
        self.grant_permission(self.profile, 'Drinkers:Beer')
        obj = Mock()
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            True)

    def test_has_object_permission_anonymous(self):
        obj = Mock()
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            False)


class TestByHttpMethodPermission(TestCase):
    def setUp(self):
        self.get_permission = Mock
        self.patch_permission = Mock
        self.post_permission = Mock
        self.put_permission = Mock
        self.permission = ByHttpMethod({
            'get': self.get_permission,
        })
        self.set_permission_mock('get', True)

    def set_permission_mock(self, method, value):
        mock = self.permission.method_permissions[method]
        mock.has_permission.return_value = value

    def set_object_permission_mock(self, method, value):
        mock = self.permission.method_permissions[method]
        mock.has_object_permission.return_value = value

    def test_get(self):
        self.request = RequestFactory().get('/')
        eq_(self.permission.has_permission(self.request, 'myview'), True)
        self.set_permission_mock('get', False)
        eq_(self.permission.has_permission(self.request, 'myview'), False)

    def test_get_obj(self):
        obj = Mock()
        self.request = RequestFactory().get('/')
        self.set_object_permission_mock('get', True)
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            True)
        self.set_object_permission_mock('get', False)
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            False)

    def test_missing_method(self):
        self.request = RequestFactory().post('/')
        eq_(self.permission.has_permission(self.request, 'myview'), False)

        obj = Mock()
        self.request = RequestFactory().post('/')
        eq_(self.permission.has_object_permission(self.request, 'myview', obj),
            False)

        self.request = RequestFactory().options('/')
        eq_(self.permission.has_permission(self.request, 'myview'), False)
