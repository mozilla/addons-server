import json
import urllib

from mock import patch
from nose.tools import eq_

from tastypie import http
from tastypie.authorization import Authorization
from tastypie.exceptions import ImmediateHttpResponse
from test_utils import RequestFactory

from amo.tests import TestCase
from mkt.api.base import MarketplaceResource
from mkt.api.serializers import Serializer


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


class TestMarketplace(TestCase):

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
