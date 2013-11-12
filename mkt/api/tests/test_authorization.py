from django.contrib.auth.models import AnonymousUser, User

from nose.tools import eq_, ok_

from amo.tests import app_factory, TestCase
from test_utils import RequestFactory

from mkt.api.authorization import (AllowOwner, AllowSelf,
                                   AnonymousReadOnlyAuthorization, flag,
                                   PermissionAuthorization, switch)
from mkt.site.fixtures import fixture

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
        self.authorization = AllowSelf()
        self.anonymous = AnonymousUser()
        self.user = User.objects.get(pk=2519)
        self.request = RequestFactory().get('/')
        self.request.user = self.anonymous
        self.request.amo_user = None

    def test_has_permission_anonymous(self):
        eq_(self.authorization.has_permission(self.request, 'myview'), False)

    def test_has_permission_user(self):
        self.request.user = self.user
        self.request.amo_user = self.request.user.get_profile()
        eq_(self.authorization.has_permission(self.request, 'myview'), True)

    def test_has_object_permission_anonymous(self):
        result = self.authorization.has_object_permission(self.request,
                                                          'myview', self.user)
        eq_(result, False)

    def test_has_object_permission_user(self):
        self.request.user = self.user
        self.request.amo_user = self.request.user.get_profile()
        result = self.authorization.has_object_permission(self.request,
                                                          'myview', self.user)
        eq_(result, True)

    def test_has_object_permission_different_user(self):
        self.request.user = User.objects.get(pk=999)
        self.request.amo_user = self.request.user.get_profile()
        result = self.authorization.has_object_permission(self.request,
                                                          'myview', self.user)
        eq_(result, False)


class TestAllowOwner(TestCase):
    fixtures = fixture('user_2519', 'user_999')

    def setUp(self):
        self.authorization = AllowOwner()
        self.anonymous = AnonymousUser()
        self.user = User.objects.get(pk=2519)
        self.request = RequestFactory().get('/')
        self.request.user = self.anonymous
        self.request.amo_user = None

    def test_has_permission_anonymous(self):
        eq_(self.authorization.has_permission(self.request, 'myview'), False)

    def test_has_permission_user(self):
        self.request.user = self.user
        self.request.amo_user = self.request.user.get_profile()
        eq_(self.authorization.has_permission(self.request, 'myview'), True)

    def test_has_object_permission_user(self):
        self.request.user = self.user
        self.request.amo_user = self.request.user.get_profile()
        result = self.authorization.has_object_permission(self.request,
                                                          'myview', self)
        eq_(result, True)

    def test_has_object_permission_different_user(self):
        self.request.user = User.objects.get(pk=999)
        self.request.amo_user = self.request.user.get_profile()
        result = self.authorization.has_object_permission(self.request,
                                                          'myview', self)
        eq_(result, False)
