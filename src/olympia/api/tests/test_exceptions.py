from django.urls import reverse
from django.http import Http404
from django.test import TestCase, override_settings

import mock

from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter
from rest_framework.settings import api_settings
from rest_framework.viewsets import GenericViewSet


class DummyViewSet(GenericViewSet):
    """Dummy test viewset that raises an exception when calling list()."""
    def list(self, *args, **kwargs):
        raise Exception('something went wrong')


test_exception = SimpleRouter()
test_exception.register('testexcept', DummyViewSet, base_name='test-exception')


@override_settings(ROOT_URLCONF=test_exception.urls)
class TestExceptionHandlerWithViewSet(TestCase):
    # The test client connects to got_request_exception, so we need to mock it
    # otherwise it would immediately re-raise the exception.
    @mock.patch('olympia.api.exceptions.got_request_exception')
    def test_view_exception(self, got_request_exception_mock):
        url = reverse('test-exception-list')
        with self.settings(DEBUG_PROPAGATE_EXCEPTIONS=False, DEBUG=False):
            response = self.client.get(url)
            assert response.status_code == 500
            assert response.data == {'detail': 'Internal Server Error'}

        assert got_request_exception_mock.send.call_count == 1
        assert got_request_exception_mock.send.call_args[0][0] == DummyViewSet
        assert isinstance(
            got_request_exception_mock.send.call_args[1]['request'], Request)

    # The test client connects to got_request_exception, so we need to mock it
    # otherwise it would immediately re-raise the exception.
    @mock.patch('olympia.api.exceptions.got_request_exception')
    def test_view_exception_debug(self, got_request_exception_mock):
        url = reverse('test-exception-list')
        with self.settings(DEBUG_PROPAGATE_EXCEPTIONS=False, DEBUG=True):
            response = self.client.get(url)
            assert response.status_code == 500
            data = response.data
            assert set(data.keys()) == set(['detail', 'traceback'])
            assert data['detail'] == 'Internal Server Error'
            assert 'Traceback (most recent call last):' in data['traceback']

        assert got_request_exception_mock.send.call_count == 1
        assert got_request_exception_mock.send.call_args[0][0] == DummyViewSet
        assert isinstance(
            got_request_exception_mock.send.call_args[1]['request'], Request)


class TestExceptionHandler(TestCase):
    def test_api_exception_handler_returns_response(self):
        exception_handler = api_settings.EXCEPTION_HANDLER

        with self.settings(DEBUG_PROPAGATE_EXCEPTIONS=False):
            try:
                raise APIException()
            except Exception as exc:
                response = exception_handler(exc, {})
                assert isinstance(response, Response)
                assert response.status_code == 500

    def test_exception_handler_returns_response_for_404(self):
        exception_handler = api_settings.EXCEPTION_HANDLER

        with self.settings(DEBUG_PROPAGATE_EXCEPTIONS=False):
            try:
                raise Http404()
            except Exception as exc:
                response = exception_handler(exc, {})
                assert isinstance(response, Response)
                assert response.status_code == 404

    def test_exception_handler_returns_response_for_403(self):
        exception_handler = api_settings.EXCEPTION_HANDLER

        with self.settings(DEBUG_PROPAGATE_EXCEPTIONS=False):
            try:
                raise PermissionDenied()
            except Exception as exc:
                response = exception_handler(exc, {})
                assert isinstance(response, Response)
                assert response.status_code == 403

    def test_non_api_exception_handler_returns_response(self):
        # Regular DRF exception handler does not return a Response for non-api
        # exceptions, but we do.
        exception_handler = api_settings.EXCEPTION_HANDLER

        with self.settings(DEBUG_PROPAGATE_EXCEPTIONS=False):
            try:
                raise Exception()
            except Exception as exc:
                response = exception_handler(exc, {})
                assert isinstance(response, Response)
                assert response.status_code == 500

    def test_api_exception_handler_with_propagation(self):
        exception_handler = api_settings.EXCEPTION_HANDLER

        with self.assertRaises(APIException):
            with self.settings(DEBUG_PROPAGATE_EXCEPTIONS=True):
                try:
                    raise APIException()
                except Exception as exc:
                    exception_handler(exc, {})

    def test_exception_handler_404_with_propagation(self):
        exception_handler = api_settings.EXCEPTION_HANDLER

        with self.assertRaises(Http404):
            with self.settings(DEBUG_PROPAGATE_EXCEPTIONS=True):
                try:
                    raise Http404()
                except Exception as exc:
                    exception_handler(exc, {})

    def test_exception_handler_403_with_propagation(self):
        exception_handler = api_settings.EXCEPTION_HANDLER

        with self.assertRaises(PermissionDenied):
            with self.settings(DEBUG_PROPAGATE_EXCEPTIONS=True):
                try:
                    raise PermissionDenied()
                except Exception as exc:
                    exception_handler(exc, {})

    def test_non_api_exception_handler_with_propagation(self):
        # Regular DRF exception handler does not return a Response for non-api
        # exceptions, but we do.
        exception_handler = api_settings.EXCEPTION_HANDLER

        with self.assertRaises(KeyError):
            with self.settings(DEBUG_PROPAGATE_EXCEPTIONS=True):
                try:
                    raise KeyError()
                except Exception as exc:
                    exception_handler(exc, {})
