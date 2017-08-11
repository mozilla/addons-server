from mock import MagicMock

from django.core.paginator import EmptyPage, InvalidPage, PageNotAnInteger

from rest_framework import generics
from rest_framework import serializers
from rest_framework import status
from rest_framework.test import APIRequestFactory

from olympia.amo.utils import paginate
from olympia.amo.tests import TestCase, ESTestCaseWithAddons
from olympia.api.paginator import (
    CustomPageNumberPagination, ESPaginator, OneOrZeroPageNumberPagination,
    Paginator)
from olympia.addons.models import Addon


class PassThroughSerializer(serializers.BaseSerializer):
    def to_representation(self, item):
        return item


class TestSearchPaginator(TestCase):

    def test_single_hit(self):
        """Test the ESPaginator only queries ES one time."""
        mocked_qs = MagicMock()
        mocked_qs.count.return_value = 42
        paginator = Paginator(mocked_qs, 5)
        # With the base paginator, requesting any page forces a count.
        paginator.page(1)
        assert paginator.count == 42
        assert mocked_qs.count.call_count == 1

        mocked_qs = MagicMock()
        mocked_qs.__getitem__().execute().hits.total = 666
        paginator = ESPaginator(mocked_qs, 5)
        # With the ES paginator, the count is fetched from the 'total' key
        # in the results.
        paginator.page(1)
        assert paginator.count == 666
        assert mocked_qs.count.call_count == 0

    def test_invalid_page(self):
        mocked_qs = MagicMock()
        paginator = ESPaginator(mocked_qs, 5)
        assert ESPaginator.max_result_window == 25000
        with self.assertRaises(InvalidPage):
            # We're fetching 5 items per page, so requesting page 5001 should
            # fail, since the max result window should is set to 25000.
            paginator.page(5000 + 1)

        with self.assertRaises(EmptyPage):
            paginator.page(0)

        with self.assertRaises(PageNotAnInteger):
            paginator.page('lol')

    def test_paginate_returns_this_paginator(self):
        request = MagicMock()
        request.GET.get.return_value = 1
        request.GET.urlencode.return_value = ''
        request.path = ''

        qs = Addon.search()
        pager = paginate(request, qs)
        assert isinstance(pager.paginator, ESPaginator)

    def test_count_legacy_compat_mode(self):
        p = ESPaginator(Addon.search(), 20, force_legacy_compat=True)

        assert p._count is None

        p.page(1)
        assert p.count == Addon.search().count()


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
