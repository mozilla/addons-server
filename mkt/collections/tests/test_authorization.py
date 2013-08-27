from django.contrib.auth.models import User

from nose.tools import ok_
from rest_framework.generics import GenericAPIView

from access.middleware import ACLMiddleware
from amo.tests import TestCase
from mkt.collections.authorization import (CuratorAuthorization,
                                           StrictCuratorAuthorization)
from mkt.collections.tests import CollectionTestMixin
from mkt.site.fixtures import fixture
from test_utils import RequestFactory


class TestCuratorAuthorization(CollectionTestMixin, TestCase):
    auth_class = CuratorAuthorization
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestCuratorAuthorization, self).setUp()
        self.collection = self.make_collection()
        self.auth = self.auth_class()
        self.user = User.objects.get(pk=2519)
        self.profile = self.user.get_profile()
        self.view = GenericAPIView()

    def give_permission(self):
        self.grant_permission(self.profile, 'Collections:Curate')

    def make_curator(self):
        self.collection.add_curator(self.profile)

    def request(self, verb):
        request = getattr(RequestFactory(), verb.lower())('/')
        request.user = self.user
        ACLMiddleware().process_request(request)
        return request

    def is_authorized(self, request):
        return self.auth.has_permission(request, self.view)

    def is_authorized_object(self, request):
        return self.auth.has_object_permission(request, self.view,
                                               self.collection)

    def test_get_list(self):
        ok_(self.is_authorized(self.request('GET')))

    def test_get_list_permission(self):
        self.give_permission()
        ok_(self.is_authorized(self.request('GET')))

    def test_post_list(self):
        ok_(not self.is_authorized(self.request('POST')))

    def test_post_list_permission(self):
        self.give_permission()
        ok_(self.is_authorized(self.request('POST')))

    def test_delete_list(self):
        ok_(not self.is_authorized(self.request('DELETE')))

    def test_delete_list_permission(self):
        self.give_permission()
        ok_(self.is_authorized(self.request('DELETE')))

    def test_get_detail(self):
        ok_(self.is_authorized_object(self.request('GET')))

    def test_get_detail_permission(self):
        self.give_permission()
        ok_(self.is_authorized_object(self.request('GET')))

    def test_get_detail_curator(self):
        self.make_curator()
        ok_(self.is_authorized_object(self.request('GET')))

    def test_get_detail_permission_curator(self):
        self.give_permission()
        self.make_curator()
        ok_(self.is_authorized_object(self.request('GET')))

    def test_post_detail(self):
        ok_(not self.is_authorized_object(self.request('POST')))

    def test_post_detail_permission(self):
        self.give_permission()
        ok_(self.is_authorized_object(self.request('POST')))

    def test_post_detail_curator(self):
        self.make_curator()
        ok_(self.is_authorized_object(self.request('POST')))

    def test_post_detail_permission_curator(self):
        self.give_permission()
        self.make_curator()
        ok_(self.is_authorized_object(self.request('POST')))

    def test_delete_detail(self):
        ok_(not self.is_authorized_object(self.request('DELETE')))

    def test_delete_detail_permission(self):
        self.give_permission()
        ok_(self.is_authorized_object(self.request('DELETE')))

    def test_delete_detail_curator(self):
        self.make_curator()
        ok_(not self.is_authorized_object(self.request('DELETE')))

    def test_delete_detail_permission_curator(self):
        self.give_permission()
        self.make_curator()
        ok_(self.is_authorized_object(self.request('DELETE')))


class TestStrictCuratorAuthorization(TestCuratorAuthorization):
    auth_class = StrictCuratorAuthorization

    def test_get_list(self):
        ok_(not self.is_authorized(self.request('GET')))

    def test_get_detail(self):
        ok_(not self.is_authorized_object(self.request('GET')))
