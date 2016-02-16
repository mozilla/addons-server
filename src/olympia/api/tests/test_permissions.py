from django.test import RequestFactory
from mock import Mock
from rest_framework.views import APIView
from rest_framework.response import Response

from olympia.access.models import Group, GroupUser
from olympia.api.permissions import GroupPermission
from olympia.amo.tests import TestCase, WithDynamicEndpoints
from olympia.users.models import UserProfile


class ProtectedView(APIView):
    permission_classes = [GroupPermission('SomeRealm', 'SomePermission')]

    def get(self, request):
        return Response('ok')


class TestGroupPermissionOnView(WithDynamicEndpoints):
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
        request.user = Mock(is_authenticated=Mock(return_value=False))
        view = Mock()
        perm = GroupPermission('SomeRealm', 'SomePermission')
        assert perm.has_permission(request, view) == False
