from django.conf import settings
from django.conf.urls import include, url
from django.core.urlresolvers import NoReverseMatch

from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from olympia.amo.tests import (
    addon_factory, reverse_ns, TestCase, WithDynamicEndpoints)


class EmptyViewSet(GenericViewSet):
    permission_classes = ()

    def list(self, request, *args, **kwargs):
        return Response({'version': request.version})


class TestNamespacing(WithDynamicEndpoints, TestCase):

    def setUp(self):
        v3_only_url = url(
            r'foo', EmptyViewSet.as_view(actions={'get': 'list'}), name='foo')
        v4_only_url = url(
            r'baa', EmptyViewSet.as_view(actions={'get': 'list'}), name='baa')
        both_url = url(
            r'yay', EmptyViewSet.as_view(actions={'get': 'list'}), name='yay')
        v3_url = url(r'v3/', include([v3_only_url, both_url], namespace='v3'))
        v4_url = url(r'v4/', include([v4_only_url, both_url], namespace='v4'))
        self.endpoint(
            include([v3_url, v4_url]),
            url_regex=r'^api/')

    def test_v3(self):
        # The unique view
        response = self.client.get(
            'api/v3/foo', HTTP_ORIGIN='testserver', follow=True)
        assert response.status_code == 200
        assert response.content == '{"version":"v3"}'
        url_ = reverse_ns('foo', api_version='v3')
        assert '/api/v3/' in url_
        # And the common one
        response = self.client.get(
            'api/v3/yay', HTTP_ORIGIN='testserver', follow=True)
        assert response.status_code == 200
        assert response.content == '{"version":"v3"}'
        url_ = reverse_ns('yay', api_version='v3')
        assert '/api/v3/' in url_
        # But no baa in v3
        response = self.client.get(
            'api/v3/baa', HTTP_ORIGIN='testserver', follow=True)
        assert response.status_code == 404
        with self.assertRaises(NoReverseMatch):
            reverse_ns('baa', api_version='v3')

    def test_v4(self):
        # The unique view
        response = self.client.get(
            'api/v4/baa', HTTP_ORIGIN='testserver', follow=True)
        assert response.status_code == 200
        assert response.content == '{"version":"v4"}'
        url_ = reverse_ns('baa', api_version='v4')
        assert '/api/v4/' in url_
        # And the common one
        response = self.client.get(
            'api/v4/yay', HTTP_ORIGIN='testserver', follow=True)
        assert response.status_code == 200
        assert response.content == '{"version":"v4"}'
        url_ = reverse_ns('yay', api_version='v4')
        assert '/api/v4/' in url_
        # But no foo in v4
        response = self.client.get(
            'api/v4/foo', HTTP_ORIGIN='testserver', follow=True)
        assert response.status_code == 404
        with self.assertRaises(NoReverseMatch):
            reverse_ns('foo', api_version='v4')

    def test_v5(self):
        # There isn't a v5 API, so this should fail
        with self.assertRaises(NoReverseMatch):
            reverse_ns('yay', 'v5')


class TestRealAPIRouting(TestCase):

    def setUp(self):
        addon_factory(slug='foo')

    def test_v3(self):
        url = reverse_ns('addon-detail', api_version='v3', args=('foo',))
        assert '/api/v3/' in url
        response = self.client.get(url, HTTP_ORIGIN='testserver')
        assert response.status_code == 200
        assert response

    def test_v4(self):
        url = reverse_ns('addon-detail', api_version='v4', args=('foo',))
        assert '/api/v4/' in url
        response = self.client.get(url, HTTP_ORIGIN='testserver')
        assert response.status_code == 200
        assert response

    def test_default(self):
        url = reverse_ns('addon-detail', args=('foo',))
        assert '/api/%s/' % settings.REST_FRAMEWORK['DEFAULT_VERSION'] in url
        response = self.client.get(url, HTTP_ORIGIN='testserver')
        assert response.status_code == 200
        assert response

    def test_v5(self):
        # There isn't a v5 API, so this should fail
        with self.assertRaises(NoReverseMatch):
            reverse_ns('addon-search', 'v5')
