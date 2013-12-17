import json
from urllib import urlencode

from django.contrib.auth.models import User

from nose.tools import ok_
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request
from rest_framework.settings import api_settings

from access.middleware import ACLMiddleware
from amo.tests import TestCase
from mkt.collections.authorization import (CanBeHeroAuthorization,
                                           CuratorAuthorization,
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


class TestCanBeHeroAuthorization(CollectionTestMixin, TestCase):
    enforced_verbs = ['POST', 'PUT']
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestCanBeHeroAuthorization, self).setUp()
        self.collection = self.make_collection()
        self.auth = CanBeHeroAuthorization()
        self.user = User.objects.get(pk=2519)
        self.profile = self.user.get_profile()
        self.view = GenericAPIView()

    def give_permission(self):
        self.grant_permission(self.profile, 'Collections:Curate')

    def is_authorized_object(self, request):
        return self.auth.has_object_permission(request, self.view,
                                               self.collection)

    def request(self, verb, qs=None, content_type='application/json',
                encoder=json.dumps, **data):
        if not qs:
            qs = ''
        request = getattr(RequestFactory(), verb.lower())
        request = request('/?' + qs, content_type=content_type,
                          data=encoder(data) if data else '')
        request.user = self.user
        ACLMiddleware().process_request(request)
        return Request(request, parsers=[parser_cls() for parser_cls in
                                         api_settings.DEFAULT_PARSER_CLASSES])

    def test_unenforced(self):
        """
        Should always pass for GET requests.
        """
        ok_(self.is_authorized_object(self.request('GET')))

    def test_no_qs_modification(self):
        """
        Non-GET requests should not be rejected if there is a can_be_true
        querystring param (which hypothetically shouldn't do anything).

        We're effectively testing that request.GET doesn't bleed into
        request.POST.
        """
        self.give_permission()
        for verb in self.enforced_verbs:
            request = self.request(verb, qs='can_be_hero=1')
            ok_(not self.auth.hero_field_modified(request), verb)

    def test_change_permission(self):
        """
        Should pass if the user is attempting to modify the can_be_hero field
        and has the permission.
        """
        self.give_permission()
        for verb in self.enforced_verbs:
            request = self.request(verb, can_be_hero=True)
            ok_(self.auth.hero_field_modified(request), verb)

    def test_change_permission_urlencode(self):
        """
        Should pass if the user is attempting to modify the can_be_hero field
        and has the permission.
        """
        self.give_permission()
        for verb in self.enforced_verbs:
            request = self.request(verb, encoder=urlencode,
                content_type='application/x-www-form-urlencoded',
                can_be_hero=True)
            ok_(self.auth.hero_field_modified(request), verb)

    def test_no_change_no_permission(self):
        """
        Should pass if the user does not have the permission and is not
        attempting to modify the can_be_hero field.
        """
        for verb in self.enforced_verbs:
            request = self.request(verb)
            ok_(self.is_authorized_object(request), verb)

    def test_no_change(self):
        """
        Should pass if the user does have the permission and is not attempting
        to modify the can_be_hero field.
        """
        self.give_permission()
        for verb in self.enforced_verbs:
            request = self.request(verb)
            ok_(self.is_authorized_object(request), verb)

    def test_post_change_no_permission(self):
        """
        Should not pass if the user is attempting to modify the can_be_hero
        field without the permission.
        """
        for verb in self.enforced_verbs:
            request = self.request(verb, can_be_hero=True)
            ok_(not self.is_authorized_object(request), verb)
