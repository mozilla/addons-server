from rest_framework import generics
from rest_framework import serializers
from rest_framework import status
from rest_framework.test import APIRequestFactory

from olympia.amo.tests import TestCase
from olympia.api.pagination import (
    CustomPageNumberPagination, OneOrZeroPageNumberPagination)


class PassThroughSerializer(serializers.BaseSerializer):
    def to_representation(self, item):
        return item


class TestCustomPageNumberPagination(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = generics.ListAPIView.as_view(
            serializer_class=PassThroughSerializer,
            queryset=range(1, 101),
            pagination_class=CustomPageNumberPagination
        )

    def test_metadata_with_page_size(self):
        request = self.factory.get('/', {'page_size': 10, 'page': 2})
        response = self.view(request)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            'page_size': 10,
            'results': range(11, 21),
            'previous': 'http://testserver/?page_size=10',
            'next': 'http://testserver/?page=3&page_size=10',
            'count': 100
        }

    def test_metadata_with_default_page_size(self):
        request = self.factory.get('/')
        response = self.view(request)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {
            'page_size': 25,
            'results': range(1, 26),
            'previous': None,
            'next': 'http://testserver/?page=2',
            'count': 100
        }


class TestOneOrZeroPageNumberPagination(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = generics.ListAPIView.as_view(
            serializer_class=PassThroughSerializer,
            queryset=range(1, 101),
            pagination_class=OneOrZeroPageNumberPagination
        )

    def test_response(self):
        # page size and page should be ignored.
        request = self.factory.get('/', {'page_size': 10, 'page': 2})
        response = self.view(request)
        assert response.data == {
            'page_size': 1,
            'results': range(1, 2),
            'previous': None,
            'next': None,
            'count': 1
        }

    def test_response_with_empty_queryset(self):
        self.view = generics.ListAPIView.as_view(
            serializer_class=PassThroughSerializer,
            queryset=[],
            pagination_class=OneOrZeroPageNumberPagination
        )
        request = self.factory.get('/')
        response = self.view(request)
        assert response.data == {
            'page_size': 1,
            'results': [],
            'previous': None,
            'next': None,
            'count': 0
        }
