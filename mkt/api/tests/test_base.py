import urllib

from django import forms

from mock import patch
from nose.tools import eq_

from rest_framework.decorators import (authentication_classes,
                                       permission_classes)
from rest_framework.response import Response

from test_utils import RequestFactory

from amo.tests import TestCase
from amo.urlresolvers import reverse

from mkt.api.base import cors_api_view
from mkt.api.tests.test_oauth import RestOAuth
from mkt.webapps.api import AppViewSet


class URLRequestFactory(RequestFactory):

    def _encode_data(self, data, content_type):
        return urllib.urlencode(data)


class TestEncoding(RestOAuth):

    def test_blah_encoded(self):
        """
        Regression test of bug #858403: ensure that a 415 (and not 500) is
        raised when an unsupported Content-Type header is passed to an API
        endpoint.
        """
        r = self.client.post(reverse('app-list'),
                             CONTENT_TYPE='application/blah',
                             data='cvan was here')
        eq_(r.status_code, 415)

    def test_bad_json(self):
        r = self.client.post(reverse('app-list'),
                             CONTENT_TYPE='application/json',
                             data="not ' json ' 5")
        eq_(r.status_code, 400)

    def test_not_json(self):
        r = self.client.get(reverse('app-list'),
                            HTTP_ACCEPT='application/blah')
        eq_(r.status_code, 406)

    @patch.object(AppViewSet, 'create')
    def test_form_encoded(self, create_mock):
        create_mock.return_value = Response()
        self.client.post(reverse('app-list'),
                         data='foo=bar',
                         content_type='application/x-www-form-urlencoded')
        eq_(create_mock.call_args[0][0].DATA['foo'], 'bar')


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
