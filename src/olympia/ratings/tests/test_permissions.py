from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from mock import mock

from olympia.amo.tests import TestCase
from olympia.ratings.permissions import CanDeleteRatingPermission
from olympia.users.models import UserProfile


class TestCanDeleteRatingPermission(TestCase):
    def setUp(self):
        self.request = RequestFactory().get('/')
        self.request.user = AnonymousUser()
        self.perm = CanDeleteRatingPermission()

    def test_has_permission_anonymous(self):
        assert not self.perm.has_permission(self.request, None)

    def test_has_permission_authenticated(self):
        self.request.user = UserProfile()
        assert self.perm.has_permission(self.request, None)

    @mock.patch('olympia.ratings.permissions.user_can_delete_review')
    def test_has_object_permission(self, user_can_delete_review_mock):
        user_can_delete_review_mock.return_value = True
        assert self.perm.has_object_permission(self.request, None, object())

    @mock.patch('olympia.ratings.permissions.user_can_delete_review')
    def test_has_object_permission_false(self, user_can_delete_review_mock):
        user_can_delete_review_mock.return_value = False
        assert not self.perm.has_object_permission(
            self.request, None, object()
        )
