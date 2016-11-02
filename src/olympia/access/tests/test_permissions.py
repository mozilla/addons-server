from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from mock import Mock
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from olympia.access.models import Group, GroupUser
from olympia.access.permissions import AclPermission
from olympia.amo.tests import TestCase, WithDynamicEndpoints
from olympia.users.models import UserProfile


class ProtectedView(APIView):
    # Use session auth for this test view because it's easy, and the goal is
    # to test the permission, not the authentication.
    authentication_classes = [SessionAuthentication]
    permission_classes = [AclPermission('SomeRealm', 'SomePermission')]

    def get(self, request):
        return Response('ok')


def myview(*args, **kwargs):
    pass


class TestAclPermissionOnView(WithDynamicEndpoints):
    # Note: be careful when testing, under the hood we're using a method that
    # relies on UserProfile.groups_list, which is cached on the UserProfile
    # instance.
    fixtures = ['base/users']

    def setUp(self):
        super(TestAclPermissionOnView, self).setUp()
        self.endpoint(ProtectedView)
        self.url = '/en-US/firefox/dynamic-endpoint'
        email = 'regular@mozilla.com'

        self.user = UserProfile.objects.get(email=email)
        group = Group.objects.create(rules='SomeRealm:SomePermission')
        GroupUser.objects.create(group=group, user=self.user)

        assert self.client.login(email=email)

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


class TestAclPermission(TestCase):

    def test_user_cannot_be_anonymous(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        view = Mock()
        perm = AclPermission('SomeRealm', 'SomePermission')
        assert not perm.has_permission(request, view)
