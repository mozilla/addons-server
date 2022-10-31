from unittest import mock

from django.conf import settings

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
            queryset=list(range(1, 101)),
            pagination_class=CustomPageNumberPagination,
        )

    def test_metadata_with_page_size(self):
        request = self.factory.get('/', {'page_size': 10, 'page': 2})
        response = self.view(request)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            'page_size': 10,
            'page_count': 10,
            'results': list(range(11, 21)),
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
            'results': list(range(1, 26)),
            'previous': None,
            'next': 'http://testserver/?page=2',
            'count': 100,
        }


class TestESPageNumberPagination(TestCustomPageNumberPagination):
    def test_next_page_never_exeeds_max_result_window(self):
        total = 50000
        mocked_qs = mock.MagicMock()
        mocked_qs.__getitem__().execute().hits.total = total

        view = generics.ListAPIView.as_view(
            serializer_class=PassThroughSerializer,
            queryset=mocked_qs,
            pagination_class=ESPageNumberPagination,
        )

        # Request the last page that still has a `next`.
        page_size = 5
        page = int(settings.ES_MAX_RESULT_WINDOW / page_size) - 1
        request = self.factory.get('/', {'page_size': page_size, 'page': page})
        response = view(request)
        assert response.data == {
            'page_size': page_size,
            'page_count': page + 1,  # We know there should be one more.
            'results': mock.ANY,
            'previous': f'http://testserver/?page={page - 1}&page_size={page_size}',
            'next': f'http://testserver/?page={page + 1}&page_size={page_size}',
            'count': total,
        }

        # Request the page that doesn't have a `next` because it's over the
        # max result window.
        page = int(settings.ES_MAX_RESULT_WINDOW / page_size)
        request = self.factory.get('/', {'page_size': page_size, 'page': page})
        response = view(request)
        assert response.data == {
            'page_size': page_size,
            'page_count': page,  # We know it should be the last one.
            'results': mock.ANY,
            'previous': f'http://testserver/?page={page - 1}&page_size={page_size}',
            'next': None,
            # We don't lie about the total count
            'count': total,
        }


class TestOneOrZeroPageNumberPagination(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = generics.ListAPIView.as_view(
            serializer_class=PassThroughSerializer,
            queryset=list(range(1, 101)),
            pagination_class=OneOrZeroPageNumberPagination,
        )

    def test_response(self):
        # page size and page should be ignored.
        request = self.factory.get('/', {'page_size': 10, 'page': 2})
        response = self.view(request)
        assert response.data == {
            'page_size': 1,
            'page_count': 1,
            'results': list(range(1, 2)),
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
