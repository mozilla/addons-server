from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from mock import Mock
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from olympia import amo
from olympia.access.models import GroupUser
from olympia.amo.tests import (
    TestCase, WithDynamicEndpoints, addon_factory, user_factory)
from olympia.api.permissions import (
    AllowAddonAuthor, AllowAnyKindOfReviewer, AllowIfPublic, AllowNone,
    AllowOwner, AllowReadOnlyIfPublic, AllowRelatedObjectPermissions,
    AllowReviewer, AllowReviewerUnlisted, AnyOf, ByHttpMethod, GroupPermission)


class ProtectedView(APIView):
    # Use session auth for this test view because it's easy, and the goal is
    # to test the permission, not the authentication.
    authentication_classes = [SessionAuthentication]
    permission_classes = [GroupPermission(
        amo.permissions.NONE)]

    def get(self, request):
        return Response('ok')


def myview(*args, **kwargs):
    pass


class TestGroupPermissionOnView(WithDynamicEndpoints):
    # Note: be careful when testing, under the hood we're using a method that
    # relies on UserProfile.groups_list, which is cached on the UserProfile
    # instance.
    def setUp(self):
        super(TestGroupPermissionOnView, self).setUp()
        self.endpoint(ProtectedView)
        self.url = '/en-US/firefox/dynamic-endpoint'
        self.user = user_factory(email='regular@mozilla.com')
        self.grant_permission(self.user, 'None:None')
        self.login(self.user)

    def test_user_must_be_in_required_group(self):
        GroupUser.objects.filter(user=self.user).delete()
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
        view = Mock(spec=[])
        perm = GroupPermission(amo.permissions.NONE)
        assert not perm.has_permission(request, view)


class TestAllowNone(TestCase):
    def test_has_permission(self):
        request = RequestFactory().get('/')
        assert not AllowNone().has_permission(request, myview)

    def test_has_object_permission(self):
        request = RequestFactory().get('/')
        assert not AllowNone().has_object_permission(request, myview, None)


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
    def setUp(self):
        self.addon = addon_factory()
        self.permission = AllowAddonAuthor()
        self.owner = user_factory()
        self.addon.addonuser_set.create(user=self.owner)
        self.request = RequestFactory().get('/')
        self.request.user = AnonymousUser()

    def test_has_permission_anonymous(self):
        assert not self.permission.has_permission(self.request, myview)

    def test_has_permission_any_authenticated_user(self):
        self.request.user = user_factory()
        assert self.request.user not in self.addon.authors.all()
        assert self.permission.has_permission(self.request, myview)

    def test_has_object_permission_owner(self):
        self.request.user = self.owner
        assert self.permission.has_object_permission(
            self.request, myview, self.addon)

    def test_has_object_permission_different_user(self):
        self.request.user = user_factory()
        assert self.request.user not in self.addon.authors.all()
        assert not self.permission.has_object_permission(
            self.request, myview, self.addon)

    def test_has_object_permission_anonymous(self):
        assert not self.permission.has_object_permission(
            self.request, myview, self.addon)


class TestAllowOwner(TestCase):
    def setUp(self):
        self.permission = AllowOwner()
        self.anonymous = AnonymousUser()
        self.user = user_factory()
        self.request = RequestFactory().get('/')
        self.request.user = self.anonymous

    def test_has_permission_anonymous(self):
        assert not self.permission.has_permission(self.request, 'myview')

    def test_has_permission_user(self):
        self.request.user = self.user
        assert self.permission.has_permission(self.request, 'myview')

    def test_has_object_permission_user(self):
        self.request.user = self.user
        obj = Mock(spec=[])
        obj.user = self.user
        assert self.permission.has_object_permission(
            self.request, 'myview', obj)

    def test_has_object_permission_no_user_on_obj(self):
        self.request.user = self.user
        obj = Mock(spec=[])
        assert not self.permission.has_object_permission(
            self.request, 'myview', obj)

    def test_has_object_permission_different_user(self):
        self.request.user = self.user
        obj = Mock(spec=[])
        obj.user = user_factory()
        assert not self.permission.has_object_permission(
            self.request, 'myview', obj)


class TestAllowReviewer(TestCase):
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
        obj = Mock(spec=[])
        obj.type = amo.ADDON_EXTENSION
        obj.has_listed_versions = lambda: True

        assert not self.permission.has_permission(request, myview)
        assert not self.permission.has_object_permission(
            request, myview, obj)

    def test_authenticated_but_not_reviewer(self):
        request = self.request_factory.get('/')
        request.user = user_factory()
        obj = Mock(spec=[])
        obj.type = amo.ADDON_EXTENSION
        obj.has_listed_versions = lambda: True
        assert self.permission.has_permission(request, myview)
        assert not self.permission.has_object_permission(
            request, myview, obj)

    def test_admin(self):
        user = user_factory()
        self.grant_permission(user, '*:*')

        for method in self.safe_methods + self.unsafe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user
            obj = Mock(spec=[])
            obj.type = amo.ADDON_EXTENSION
            obj.has_listed_versions = lambda: True
            assert self.permission.has_permission(request, myview)
            assert self.permission.has_object_permission(
                request, myview, obj)

    def test_reviewer_tools_access_read_only(self):
        user = user_factory()
        self.grant_permission(user, 'ReviewerTools:View')
        obj = Mock(spec=[])
        obj.type = amo.ADDON_EXTENSION
        obj.has_listed_versions = lambda: True

        for method in self.safe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user
            assert self.permission.has_permission(request, myview)
            assert self.permission.has_object_permission(
                request, myview, obj)

        for method in self.unsafe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user
            # When not checking the object, we have permission because we're
            # authenticated.
            assert self.permission.has_permission(request, myview)
            assert not self.permission.has_object_permission(
                request, myview, obj)

    def test_legacy_reviewer(self):
        user = user_factory()
        self.grant_permission(user, 'Addons:Review')
        obj = Mock(spec=[])
        obj.type = amo.ADDON_EXTENSION
        obj.has_listed_versions = lambda: True

        for method in self.safe_methods + self.unsafe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user
            assert self.permission.has_permission(request, myview)
            assert self.permission.has_object_permission(
                request, myview, obj)

        # Does not have access to static themes.
        obj.type = amo.ADDON_STATICTHEME
        for method in self.safe_methods + self.unsafe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user
            # When not checking the object, we have permission because we're
            # authenticated.
            assert self.permission.has_permission(request, myview)
            assert not self.permission.has_object_permission(
                request, myview, obj)

    def test_post_reviewer(self):
        user = user_factory()
        self.grant_permission(user, 'Addons:PostReview')
        obj = Mock(spec=[])
        obj.type = amo.ADDON_EXTENSION
        obj.has_listed_versions = lambda: True

        for method in self.safe_methods + self.unsafe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user
            assert self.permission.has_permission(request, myview)
            assert self.permission.has_object_permission(
                request, myview, obj)

        # Does not have access to static themes.
        obj.type = amo.ADDON_STATICTHEME
        for method in self.safe_methods + self.unsafe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user
            # When not checking the object, we have permission because we're
            # authenticated.
            assert self.permission.has_permission(request, myview)
            assert not self.permission.has_object_permission(
                request, myview, obj)

    def test_theme_reviewer(self):
        user = user_factory()
        self.grant_permission(user, 'Addons:ThemeReview')
        obj = Mock(spec=[])
        obj.type = amo.ADDON_STATICTHEME
        obj.has_listed_versions = lambda: True

        for method in self.safe_methods + self.unsafe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user
            assert self.permission.has_permission(request, myview)
            assert self.permission.has_object_permission(
                request, myview, obj)

        # Does not have access to other extensions.
        obj.type = amo.ADDON_EXTENSION
        for method in self.safe_methods + self.unsafe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user
            # When not checking the object, we have permission because we're
            # authenticated.
            assert self.permission.has_permission(request, myview)
            assert not self.permission.has_object_permission(
                request, myview, obj)

    def test_no_listed_version_reviewer(self):
        user = user_factory()
        self.grant_permission(user, 'Addons:Review')
        obj = Mock(spec=[])
        obj.type = amo.ADDON_EXTENSION
        obj.has_listed_versions = lambda: False

        for method in self.safe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user

            # When not checking the object, we have permission because we're
            # authenticated.
            assert self.permission.has_permission(request, myview)

            # It doesn't work with the object though, since
            # has_listed_versions() is returning False, we don't have enough
            # permissions, being a "simple" reviewer.
            assert not self.permission.has_object_permission(
                request, myview, obj)

        for method in self.unsafe_methods:
            request = getattr(self.request_factory, method)('/')
            request.user = user

            # When not checking the object, we have permission because we're
            # authenticated.
            assert self.permission.has_permission(request, myview)

            # As above it doesn't work with the object though.
            assert not self.permission.has_object_permission(
                request, myview, obj)


class TestAllowAnyKindOfReviewer(TestCase):
    # Note: be careful when testing, under the hood we're using a method that
    # relies on UserProfile.groups_list, which is cached on the UserProfile
    # instance.
    def setUp(self):
        self.permission = AllowAnyKindOfReviewer()
        self.request = RequestFactory().post('/')

    def test_user_cannot_be_anonymous(self):
        self.request.user = AnonymousUser()
        obj = Mock(spec=[])
        assert not self.permission.has_permission(self.request, myview)
        assert not self.permission.has_object_permission(
            self.request, myview, obj)

    def test_authenticated_but_not_reviewer(self):
        self.request.user = user_factory()
        obj = Mock(spec=[])
        assert not self.permission.has_permission(self.request, myview)
        assert not self.permission.has_object_permission(
            self.request, myview, obj)

    def test_admin(self):
        self.request.user = user_factory()
        self.grant_permission(self.request.user, '*:*')
        obj = Mock(spec=[])

        assert self.permission.has_permission(self.request, myview)
        assert self.permission.has_object_permission(self.request, myview, obj)

    def test_regular_reviewer(self):
        self.request.user = user_factory()
        self.grant_permission(self.request.user, 'Addons:Review')
        obj = Mock(spec=[])

        assert self.permission.has_permission(self.request, myview)
        assert self.permission.has_object_permission(self.request, myview, obj)

    def test_unlisted_reviewer(self):
        self.request.user = user_factory()
        self.grant_permission(self.request.user, 'Addons:ReviewUnlisted')
        obj = Mock(spec=[])
        obj.has_unlisted_versions = lambda: True

        assert self.permission.has_permission(self.request, myview)
        assert self.permission.has_object_permission(self.request, myview, obj)

    def test_post_reviewer(self):
        self.request.user = user_factory()
        self.grant_permission(self.request.user, 'Addons:PostReview')
        obj = Mock(spec=[])

        assert self.permission.has_permission(self.request, myview)
        assert self.permission.has_object_permission(self.request, myview, obj)


class TestAllowUnlistedReviewer(TestCase):
    # Note: be careful when testing, under the hood we're using a method that
    # relies on UserProfile.groups_list, which is cached on the UserProfile
    # instance.
    def setUp(self):
        self.permission = AllowReviewerUnlisted()
        self.request = RequestFactory().post('/')

    def test_user_cannot_be_anonymous(self):
        self.request.user = AnonymousUser()
        obj = Mock(spec=[])
        obj.has_unlisted_versions = lambda: True
        assert not self.permission.has_permission(self.request, myview)
        assert not self.permission.has_object_permission(
            self.request, myview, obj)

    def test_authenticated_but_not_reviewer(self):
        self.request.user = user_factory()
        obj = Mock(spec=[])
        obj.has_unlisted_versions = lambda: True
        assert not self.permission.has_permission(self.request, myview)
        assert not self.permission.has_object_permission(
            self.request, myview, obj)

    def test_admin(self):
        self.request.user = user_factory()
        self.grant_permission(self.request.user, '*:*')
        obj = Mock(spec=[])
        obj.has_unlisted_versions = lambda: True

        assert self.permission.has_permission(self.request, myview)
        assert self.permission.has_object_permission(self.request, myview, obj)

    def test_regular_reviewer(self):
        self.request.user = user_factory()
        self.grant_permission(self.request.user, 'Addons:Review')
        obj = Mock(spec=[])
        obj.has_unlisted_versions = lambda: True

        assert not self.permission.has_permission(self.request, myview)
        assert not self.permission.has_object_permission(
            self.request, myview, obj)

    def test_unlisted_reviewer(self):
        self.request.user = user_factory()
        self.grant_permission(self.request.user, 'Addons:ReviewUnlisted')
        obj = Mock(spec=[])
        obj.has_unlisted_versions = lambda: True

        assert self.permission.has_permission(self.request, myview)
        assert self.permission.has_object_permission(self.request, myview, obj)

    def test_object_with_listed_versions_but_no_unlisted_versions(self):
        self.request.user = user_factory()
        self.grant_permission(self.request.user, 'Addons:ReviewUnlisted')
        obj = Mock(spec=[])
        obj.has_unlisted_versions = lambda: False
        obj.has_listed_versions = lambda: True

        assert self.permission.has_permission(self.request, myview)
        assert not self.permission.has_object_permission(
            self.request, myview, obj)

    def test_object_with_no_unlisted_versions_and_no_listed_versions(self):
        self.request.user = user_factory()
        self.grant_permission(self.request.user, 'Addons:ReviewUnlisted')
        obj = Mock(spec=[])
        obj.has_unlisted_versions = lambda: False
        obj.has_listed_versions = lambda: False

        assert self.permission.has_permission(self.request, myview)
        assert self.permission.has_object_permission(
            self.request, myview, obj)


class TestAllowIfPublic(TestCase):
    def setUp(self):
        self.permission = AllowIfPublic()
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
            assert self.permission.has_permission(
                self.request(verb), myview)

    def test_has_object_permission_public(self):
        obj = Mock(spec=['is_public'])
        obj.is_public.return_value = True

        for verb in self.safe_methods:
            assert self.permission.has_object_permission(
                self.request(verb), myview, obj)

        for verb in self.unsafe_methods:
            assert self.permission.has_object_permission(
                self.request(verb), myview, obj)

    def test_has_object_permission_not_public(self):
        obj = Mock(spec=['is_public'])
        obj.is_public.return_value = False

        for verb in self.unsafe_methods + self.safe_methods:
            assert not self.permission.has_object_permission(
                self.request(verb), myview, obj)


class TestAllowReadOnlyIfPublic(TestCase):
    def setUp(self):
        self.permission = AllowReadOnlyIfPublic()
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
        obj = Mock(spec=['is_public'])
        obj.is_public.return_value = True

        for verb in self.safe_methods:
            assert self.permission.has_object_permission(
                self.request(verb), myview, obj)

        for verb in self.unsafe_methods:
            assert not self.permission.has_object_permission(
                self.request(verb), myview, obj)

    def test_has_object_permission_not_public(self):
        obj = Mock(spec=['is_public'])
        obj.is_public.return_value = False

        for verb in self.unsafe_methods + self.safe_methods:
            assert not self.permission.has_object_permission(
                self.request(verb), myview, obj)


class TestByHttpMethod(TestCase):
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
        assert self.permission.has_permission(self.request, 'myview') is True
        self.set_permission_mock('get', False)
        assert self.permission.has_permission(self.request, 'myview') is False

    def test_get_obj(self):
        obj = Mock(spec=[])
        self.request = RequestFactory().get('/')
        self.set_object_permission_mock('get', True)
        assert self.permission.has_object_permission(
            self.request, 'myview', obj) is True

        self.set_object_permission_mock('get', False)
        assert self.permission.has_object_permission(
            self.request, 'myview', obj) is False

    def test_missing_method(self):
        self.request = RequestFactory().post('/')
        with self.assertRaises(MethodNotAllowed):
            self.permission.has_permission(self.request, 'myview')

        obj = Mock(spec=[])
        self.request = RequestFactory().post('/')
        with self.assertRaises(MethodNotAllowed):
            self.permission.has_object_permission(self.request, 'myview', obj)

        self.request = RequestFactory().options('/')
        with self.assertRaises(MethodNotAllowed):
            self.permission.has_permission(self.request, 'myview')


class TestAllowRelatedObjectPermissions(TestCase):
    def setUp(self):
        self.permission = AllowRelatedObjectPermissions(
            'test_property', [AllowOwner, AllowAny])
        self.allowed_user = user_factory()
        self.related_obj = Mock(user=self.allowed_user)
        self.obj = Mock(test_property=self.related_obj)
        self.request = RequestFactory().post('/')
        self.request.user = self.allowed_user

    def test_all_must_pass(self):
        assert self.permission.has_permission(
            self.request, 'myview') is True

        self.request.user = AnonymousUser()
        assert self.permission.has_permission(
            self.request, 'myview') is False

    def test_all_must_pass_object(self):
        assert self.permission.has_object_permission(
            self.request, 'myview', self.obj) is True

        self.request.user = AnonymousUser()
        assert self.permission.has_permission(
            self.request, 'myview') is False
