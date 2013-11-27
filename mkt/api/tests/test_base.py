import json
import urllib

from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied

from mock import patch
from nose.tools import eq_, ok_

from rest_framework.decorators import (authentication_classes,
                                       permission_classes)
from rest_framework.response import Response

from tastypie import http
from tastypie.authentication import Authentication
from tastypie.authorization import Authorization
from tastypie.exceptions import ImmediateHttpResponse
from tastypie.throttle import BaseThrottle
from test_utils import RequestFactory

from access.middleware import ACLMiddleware
from amo.tests import TestCase
from mkt.api.base import (AppViewSet, cors_api_view, CORSResource, handle_500,
                          MarketplaceResource)
from mkt.api.http import HttpTooManyRequests
from mkt.api.serializers import Serializer
from mkt.receipts.tests.test_views import RawRequestFactory
from mkt.site.fixtures import fixture


class SampleResource(MarketplaceResource):

    class Meta(object):
        authorization = Authorization()
        serializer = Serializer()
        object_class = dict

    def get_resource_uri(self, bundle):
        return ''


class URLRequestFactory(RequestFactory):

    def _encode_data(self, data, content_type):
        return urllib.urlencode(data)


class TestLogging(TestCase):

    def setUp(self):
        self.resource = SampleResource()
        self.request = URLRequestFactory().get('/')
        self.exception_cls = type('SampleException', (Exception,), {})

    @patch('mkt.api.base.tasty_log.error')
    def test_logging(self, mock_error_log):
        msg = 'oops'
        handle_500(self.resource, self.request, self.exception_cls(msg))
        eq_(mock_error_log.call_count, 1)
        ok_(self.exception_cls.__name__ in mock_error_log.call_args[0][0])
        ok_(msg in mock_error_log.call_args[0][0])
        ok_('exc_info' in mock_error_log.call_args[1])


class TestEncoding(TestCase):

    def setUp(self):
        self.resource = SampleResource()
        self.request = URLRequestFactory().post('/')

    def test_blah_encoded(self):
        """
        Regression test of bug #858403: ensure that a 400 (and not 500) is
        raised when an unsupported Content-Type header is passed to an API
        endpoint.
        """
        self.request.META['CONTENT_TYPE'] = 'application/blah'
        with self.assertImmediate(http.HttpBadRequest):
            self.resource.dispatch('list', self.request)

    def test_no_contenttype(self):
        del self.request.META['CONTENT_TYPE']
        with self.assertImmediate(http.HttpBadRequest):
            self.resource.dispatch('list', self.request)

    def test_bad_json(self):
        request = RawRequestFactory().post('/', "not ' json ' 5")
        with self.assertImmediate(http.HttpBadRequest):
            self.resource.dispatch('list', request)

    def test_not_json(self):
        self.request.META['HTTP_ACCEPT'] = 'application/blah'
        with self.assertImmediate(http.HttpBadRequest):
            self.resource.dispatch('list', self.request)

    def test_errors(self):
        self.request.META['HTTP_ACCEPT'] = 'application/blah'
        self.request.META['CONTENT_TYPE'] = 'application/blah'
        try:
            self.resource.dispatch('list', self.request)
        except ImmediateHttpResponse, error:
            pass

        res = json.loads(error.response.content)['error_message']['__all__']
        eq_([u"Unsupported Content-Type header 'application/blah'",
             u"Unsupported Accept header 'application/blah'"], res)

    @patch.object(SampleResource, 'obj_create')
    def test_form_encoded(self, obj_create):
        request = URLRequestFactory().post('/', data={'foo': 'bar'},
            content_type='application/x-www-form-urlencoded')
        self.resource.dispatch('list', request)
        eq_(obj_create.call_args[0][0].data, {'foo': 'bar'})

    @patch.object(SampleResource, 'obj_create')
    def test_permission(self, obj_create):
        request = RequestFactory().post('/', data={},
            content_type='application/json')
        obj_create.side_effect = PermissionDenied
        with self.assertImmediate(http.HttpForbidden):
            self.resource.dispatch('list', request)


class FakeAuthentication(Authentication):
    def get_identifier(self, request):
        return 'fake'


class ThrottleResource(MarketplaceResource):

    class Meta(object):
        authorization = Authorization()
        throttle = BaseThrottle()


class TestThrottling(TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestThrottling, self).setUp()
        self.resource = ThrottleResource()
        self.request = RequestFactory().post('/')
        self.user = User.objects.get(pk=2519)
        self.request.user = self.user
        self.throttle = self.resource._meta.throttle
        self.request.META['CONTENT_TYPE'] = 'application/x-www-form-urlencoded'
        self.mocked_sbt = patch.object(self.throttle, 'should_be_throttled')

    def no_throttle_expected(self, request=None):
        if request is None:
            request = self.request
        try:
            self.resource.throttle_check(request)
        except ImmediateHttpResponse, e:
            if isinstance(e.response, HttpTooManyRequests):
                self.fail('Unexpected 429')
            raise e

    def throttle_expected(self):
        with self.assertImmediate(HttpTooManyRequests):
            self.resource.throttle_check(self.request)

    def test_get_throttle_identifiers_multiple_auth(self):
        self.resource._meta.authentication = [FakeAuthentication(),
                                              FakeAuthentication()]
        identifiers = list(self.resource.get_throttle_identifiers(self.request))
        eq_(identifiers, ['fake'])

    def test_should_throttle(self):
        with self.mocked_sbt as sbt:
            sbt.return_value = True
            self.throttle_expected()
            eq_(self.throttle.should_be_throttled.call_count, 1)

    def test_shouldnt_throttle(self):
        with self.mocked_sbt as sbt:
            sbt.return_value = False
            self.no_throttle_expected()
            eq_(self.throttle.should_be_throttled.call_count, 1)

    def test_GET_shouldnt_throttle(self):
        with self.mocked_sbt as sbt:
            sbt.return_value = True
            self.no_throttle_expected(RequestFactory().get('/'))
            eq_(self.throttle.should_be_throttled.call_count, 0)

    def test_unthrottled_user(self):
        self.grant_permission(self.user.get_profile(), 'Apps:APIUnthrottled')
        ACLMiddleware().process_request(self.request)
        with self.mocked_sbt as sbt:
            sbt.return_value = True
            self.no_throttle_expected()
            eq_(self.throttle.should_be_throttled.call_count, 0)

    def test_throttled_user_setting_enabled(self):
        with self.settings(API_THROTTLE=True):
            ACLMiddleware().process_request(self.request)
            with self.mocked_sbt as sbt:
                sbt.return_value = True
                self.throttle_expected()
                eq_(self.throttle.should_be_throttled.call_count, 1)

    def test_throttled_user_setting_disabled(self):
        with self.settings(API_THROTTLE=False):
            ACLMiddleware().process_request(self.request)
            with self.mocked_sbt as sbt:
                sbt.return_value = True
                self.no_throttle_expected()
                eq_(self.throttle.should_be_throttled.call_count, 0)


class FilteredCORS(CORSResource, MarketplaceResource):

    class Meta(object):
        cors_allowed = ['get', 'put']


class UnfilteredCORS(CORSResource, MarketplaceResource):
    pass


class TestCORSResource(TestCase):

    def test_filtered(self):
        request = RequestFactory().get('/')
        FilteredCORS().method_check(request, allowed=['get'])
        eq_(request.CORS, ['get', 'put'])

    def test_unfiltered(self):
        request = RequestFactory().get('/')
        UnfilteredCORS().method_check(request, allowed=['get'])
        eq_(request.CORS, ['get'])


class TestCORSWrapper(TestCase):
    def test_cors(self):
        @cors_api_view(['GET', 'PATCH'])
        @authentication_classes([])
        @permission_classes([])
        def foo(request):
            return Response()
        request = RequestFactory().get('/')
        r = foo(request)
        eq_(request.CORS, ['GET', 'PATCH'])


class Form(forms.Form):
    app = forms.ChoiceField(choices=(('valid', 'valid'),))


class TestAppViewSet(TestCase):

    def setUp(self):
        self.request = RequestFactory().get('/')
        self.viewset = AppViewSet()
        self.viewset.action_map = {}
        self.viewset.form = Form

    def test_ok(self):
        self.viewset.initialize_request(self.request, pk='valid')
        ok_(self.viewset.app)

    def test_not_ok(self):
        self.viewset.initialize_request(self.request, pk='invalid')
        eq_(self.viewset.app, None)
