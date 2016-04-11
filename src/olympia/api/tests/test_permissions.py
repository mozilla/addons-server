from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from mock import Mock
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon
from olympia.api.permissions import (
    AllowAddonAuthor, AllowReadOnlyIfPublicAndListed, AllowReviewer,
    AllowReviewerUnlisted, AnyOf, GroupPermission)
from olympia.amo.tests import TestCase, WithDynamicEndpoints
from olympia.users.models import UserProfile


class ProtectedView(APIView):
    # Use session auth for this test view because it's easy, and the goal is
    # to test the permission, not the authentication.
    authentication_classes = [SessionAuthentication]
    permission_classes = [GroupPermission('SomeRealm', 'SomePermission')]

    def get(self, request):
        return Response('ok')


class AllowNone(BasePermission):
    """A permission class that never allows access, for testing."""
    def has_permission(self, request, view):
        return False

    def has_object_permission(self, request, view, obj):
        return False


def myview(*args, **kwargs):
    pass


class TestGroupPermissionOnView(WithDynamicEndpoints):
    # Note: be careful when testing, under the hood we're using a method that
    # relies on UserProfile.groups_list, which is cached on the UserProfile
    # instance.
    fixtures = ['base/users']

    def setUp(self):
        super(TestGroupPermissionOnView, self).setUp()
        self.endpoint(ProtectedView)
        self.url = '/en-US/firefox/dynamic-endpoint'
        email = 'regular@mozilla.com'

        self.user = UserProfile.objects.get(email=email)
        group = Group.objects.create(rules='SomeRealm:SomePermission')
        GroupUser.objects.create(group=group, user=self.user)

        assert self.client.login(username=email,
                                 password='password')

    def test_user_must_be_in_required_group(self):
        self.user.groups.all().delete()
        res = self.client.get(self.url)
        assert res.status_code == 403, res.content
        assert res.data['detail'] == (
            'You do not have permission to perform this action.')

    def test_view_is_executed(self):
        res = self.client.get(self.url)
        assert res.status_code == 200, res.content
        assert res.content == '"ok"'


class TestGroupPermission(TestCase):

    def test_user_cannot_be_anonymous(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        view = Mock()
        perm = GroupPermission('SomeRealm', 'SomePermission')
        assert perm.has_permission(request, view) is False


class TestAnyOf(TestCase):
    def test_has_permission(self):
        request = RequestFactory().get('/')
        assert AnyOf(AllowNone, AllowAny)().has_permission(request, myview)
        assert AnyOf(AllowAny, AllowNone)().has_permission(request, myview)

    def test_has_permission_fail(self):
        request = RequestFactory().get('/')
        assert not AnyOf(AllowNone, AllowNone)().has_permission(
            request, myview)

    def test_has_object_permission(self):
        request = RequestFactory().get('/')
        assert AnyOf(AllowNone, AllowAny)().has_object_permission(
            request, myview, None)
        assert AnyOf(AllowAny, AllowNone)().has_object_permission(
            request, myview, None)

    def test_has_object_permission_fail(self):
        request = RequestFactory().get('/')
        assert not AnyOf(AllowNone, AllowNone)().has_object_permission(
            request, myview, None)

    def test_has_object_permission_partial_fail(self):
        """Test that AnyOf.has_object_permission() does not allow access when
        a permission class returns False for has_permission() without having
        a has_object_permission() implementation."""

        class NoObjectPerm(BasePermission):
            # This class will not grant access because we do check
            # has_permission() on top of just has_object_permission().
            def has_permission(self, request, view):
                return False

        class NoPerm(BasePermission):
            # This class will not grant access either when checking
            # has_object_permission() since it directly returns False.
            def has_object_permission(self, request, view, obj):
                return False

        request = RequestFactory().get('/')
        assert not AnyOf(NoObjectPerm, NoPerm)().has_object_permission(
            request, myview, None)


class TestAllowAddonAuthor(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.permission = AllowAddonAuthor()
        self.owner = self.addon.authors.all()[0]
        self.request = RequestFactory().get('/')
        self.request.user = AnonymousUser()

    def test_has_permission_anonymous(self):
        assert not self.permission.has_permission(self.request, myview)

    def test_has_permission_any_authenticated_user(self):
        self.request.user = UserProfile.objects.get(pk=999)
        assert self.request.user not in self.addon.authors.all()
        assert self.permission.has_permission(self.request, myview)

    def test_has_object_permission_user(self):
        self.request.user = self.owner
        assert self.permission.has_object_permission(
            self.request, myview, self.addon)

    def test_has_object_permission_different_user(self):
        self.request.user = UserProfile.objects.get(pk=999)
        assert self.request.user not in self.addon.authors.all()
        assert not self.permission.has_object_permission(
            self.request, myview, self.addon)

    def test_has_object_permission_anonymous(self):
        assert not self.permission.has_object_permission(
            self.request, myview, self.addon)


class TestAllowReviewer(TestCase):
    fixtures = ['base/users']

    # Note: be careful when testing, under the hood we're using a method that
    # relies on UserProfile.groups_list, which is cached on the UserProfile
    # instance.
    def setUp(self):
        self.permission = AllowReviewer()
        self.request_factory = RequestFactory()
        self.unsafe_methods = ('patch', 'post', 'put', 'delete')
        self.safe_methods = ('get', 'options', 'head')

    def test_user_cannot_be_anonymous(self):
        request = self.request_factory.get('/')
        request.user = AnonymousUser()
        assert not self.permission.has_permission(request, myview)
        assert not self.permission.has_object_permission(
            request, myview, Mock())

    def test_authenticated_but_not_reviewer(self):
        request = self.request_factory.get('/')
        request.user = UserProfile.objects.get(pk=999)
        assert not self.permission.has_permission(request, myview)
        assert not self.permission.has_object_permission(
            request, myview, Mock())

    def test_admin(self):
        user = UserProfile.objects.get(email='admin@mozilla.com')

        for method in self.safe_methods + self.unsafe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user
            assert self.permission.has_permission(request, myview)
            assert self.permission.has_object_permission(
                request, myview, Mock())

    def test_reviewer_tools_access_read_only(self):
        user = UserProfile.objects.get(pk=999)
        group = Group.objects.create(
            name='ReviewerTools Viewer', rules='ReviewerTools:View')
        GroupUser.objects.create(user=user, group=group)

        for method in self.safe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user
            assert self.permission.has_permission(request, myview)
            assert self.permission.has_object_permission(
                request, myview, Mock())

        for method in self.unsafe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user
            assert not self.permission.has_permission(request, myview)
            assert not self.permission.has_object_permission(
                request, myview, Mock())

    def test_actual_reviewer(self):
        user = UserProfile.objects.get(email='editor@mozilla.com')

        for method in self.safe_methods + self.unsafe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user
            assert self.permission.has_permission(request, myview)
            assert self.permission.has_object_permission(
                request, myview, Mock())


class TestAllowUnlistedReviewer(TestCase):
    fixtures = ['base/users']

    # Note: be careful when testing, under the hood we're using a method that
    # relies on UserProfile.groups_list, which is cached on the UserProfile
    # instance.
    def setUp(self):
        self.permission = AllowReviewerUnlisted()
        self.request = RequestFactory().get('/')

    def test_user_cannot_be_anonymous(self):
        self.request.user = AnonymousUser()
        obj = Mock()
        obj.is_listed = False
        assert not self.permission.has_permission(self.request, myview)
        assert not self.permission.has_object_permission(
            self.request, myview, obj)

    def test_authenticated_but_not_reviewer(self):
        self.request.user = UserProfile.objects.get(pk=999)
        obj = Mock()
        obj.is_listed = False
        assert not self.permission.has_permission(self.request, myview)
        assert not self.permission.has_object_permission(
            self.request, myview, obj)

    def test_admin(self):
        self.request.user = UserProfile.objects.get(email='admin@mozilla.com')
        obj = Mock()
        obj.is_listed = False

        assert self.permission.has_permission(self.request, myview)
        assert self.permission.has_object_permission(self.request, myview, obj)

    def test_unlisted_reviewer(self):
        self.request.user = UserProfile.objects.get(
            email='senioreditor@mozilla.com')
        obj = Mock()
        obj.is_listed = False

        assert self.permission.has_permission(self.request, myview)
        assert self.permission.has_object_permission(self.request, myview, obj)


class TestAllowReadOnlyIfPublicAndListed(TestCase):
    def setUp(self):
        self.permission = AllowReadOnlyIfPublicAndListed()
        self.request_factory = RequestFactory()
        self.unsafe_methods = ('patch', 'post', 'put', 'delete')
        self.safe_methods = ('get', 'options', 'head')

    def request(self, verb):
        request = getattr(self.request_factory, verb)('/')
        request.user = AnonymousUser()
        return request

    def test_has_permission(self):
        for verb in self.safe_methods:
            assert self.permission.has_permission(self.request(verb), myview)
        for verb in self.unsafe_methods:
            assert not self.permission.has_permission(
                self.request(verb), myview)

    def test_has_object_permission_public(self):
        obj = Mock()
        obj.is_public.return_value = True
        obj.is_listed = True

        for verb in self.safe_methods:
            assert self.permission.has_object_permission(
                self.request(verb), myview, obj)

        for verb in self.unsafe_methods:
            assert not self.permission.has_object_permission(
                self.request(verb), myview, obj)

    def test_has_object_permission_not_public(self):
        obj = Mock()
        obj.is_public.return_value = False
        obj.is_listed = True

        for verb in self.unsafe_methods + self.safe_methods:
            assert not self.permission.has_object_permission(
                self.request(verb), myview, obj)

    def test_has_object_permission_not_listed(self):
        obj = Mock()
        obj.is_public.return_value = True
        obj.is_listed = False

        for verb in self.unsafe_methods + self.safe_methods:
            assert not self.permission.has_object_permission(
                self.request(verb), myview, obj)

    def test_has_object_permission_not_listed_nor_public(self):
        obj = Mock()
        obj.is_public.return_value = False
        obj.is_listed = False

        for verb in self.unsafe_methods + self.safe_methods:
            assert not self.permission.has_object_permission(
                self.request(verb), myview, obj)
