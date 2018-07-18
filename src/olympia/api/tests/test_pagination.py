import mock

from rest_framework import generics, serializers, status
from rest_framework.test import APIRequestFactory

from olympia.amo.tests import TestCase
from olympia.api.pagination import (
    CustomPageNumberPagination,
    ESPageNumberPagination,
    OneOrZeroPageNumberPagination,
)


class PassThroughSerializer(serializers.BaseSerializer):
    def to_representation(self, item):
        return item


class TestCustomPageNumberPagination(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = generics.ListAPIView.as_view(
            serializer_class=PassThroughSerializer,
            queryset=range(1, 101),
            pagination_class=CustomPageNumberPagination,
        )

    def test_metadata_with_page_size(self):
        request = self.factory.get('/', {'page_size': 10, 'page': 2})
        response = self.view(request)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            'page_size': 10,
            'page_count': 10,
            'results': range(11, 21),
            'previous': 'http://testserver/?page_size=10',
            'next': 'http://testserver/?page=3&page_size=10',
            'count': 100,
        }

    def test_metadata_with_default_page_size(self):
        request = self.factory.get('/')
        response = self.view(request)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            'page_size': 25,
            'page_count': 4,
            'results': range(1, 26),
            'previous': None,
            'next': 'http://testserver/?page=2',
            'count': 100,
        }


class TestESPageNumberPagination(TestCustomPageNumberPagination):
    def test_next_page_never_exeeds_max_result_window(self):
        mocked_qs = mock.MagicMock()
        mocked_qs.__getitem__().execute().hits.total = 30000

        view = generics.ListAPIView.as_view(
            serializer_class=PassThroughSerializer,
            queryset=mocked_qs,
            pagination_class=ESPageNumberPagination,
        )

        request = self.factory.get('/', {'page_size': 5, 'page': 4999})
        response = view(request)
        assert response.data == {
            'page_size': 5,
            'page_count': 5000,
            'results': mock.ANY,
            'previous': 'http://testserver/?page=4998&page_size=5',
            'next': 'http://testserver/?page=5000&page_size=5',
            'count': 30000,
        }

        request = self.factory.get('/', {'page_size': 5, 'page': 5000})
        response = view(request)
        assert response.data == {
            'page_size': 5,
            'page_count': 5000,
            'results': mock.ANY,
            'previous': 'http://testserver/?page=4999&page_size=5',
            'next': None,
            # We don't lie about the total count
            'count': 30000,
        }


class TestOneOrZeroPageNumberPagination(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = generics.ListAPIView.as_view(
            serializer_class=PassThroughSerializer,
            queryset=range(1, 101),
            pagination_class=OneOrZeroPageNumberPagination,
        )

    def test_response(self):
        # page size and page should be ignored.
        request = self.factory.get('/', {'page_size': 10, 'page': 2})
        response = self.view(request)
        assert response.data == {
            'page_size': 1,
            'page_count': 1,
            'results': range(1, 2),
            'previous': None,
            'next': None,
            'count': 1,
        }

    def test_response_with_empty_queryset(self):
        self.view = generics.ListAPIView.as_view(
            serializer_class=PassThroughSerializer,
            queryset=[],
            pagination_class=OneOrZeroPageNumberPagination,
        )
        request = self.factory.get('/')
        response = self.view(request)
        assert response.data == {
            'page_size': 1,
            'page_count': 1,
            'results': [],
            'previous': None,
            'next': None,
            'count': 0,
        }
