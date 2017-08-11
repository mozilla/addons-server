from collections import OrderedDict

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from django.core.paginator import (
    EmptyPage, InvalidPage, Page, PageNotAnInteger, Paginator)


class ESPaginator(Paginator):
    """
    A better paginator for search results
    The normal Paginator does a .count() query and then a slice. Since ES
    results contain the total number of results, we can take an optimistic
    slice and then adjust the count.

    :param use_elasticsearch_dsl:
        Used to activate support for our elasticsearch-dsl based pagination
        implementation. elasticsearch-dsl is being used in the v3 API while
        we have our own wrapper implementation in :mod:`olympia.amo.search`.
    """

    # Maximum result position. Should match 'index.max_result_window' ES
    # setting if present. ES defaults to 10000 but we'd like more to make sure
    # all our extensions can be found if searching without a query and
    # paginating through all results.
    max_result_window = 25000

    def __init__(self, *args, **kwargs):
        self.use_elasticsearch_dsl = kwargs.pop('use_elasticsearch_dsl', True)
        Paginator.__init__(self, *args, **kwargs)

    def validate_number(self, number):
        """
        Validates the given 1-based page number.
        This class overrides the default behavior and ignores the upper bound.
        """
        try:
            number = int(number)
        except (TypeError, ValueError):
            raise PageNotAnInteger('That page number is not an integer')
        if number < 1:
            raise EmptyPage('That page number is less than 1')
        return number

    def page(self, number):
        """
        Returns a page object.
        This class overrides the default behavior and ignores "orphans" and
        assigns the count from the ES result to the Paginator.
        """
        number = self.validate_number(number)
        bottom = (number - 1) * self.per_page
        top = bottom + self.per_page

        if bottom > self.max_result_window:
            raise InvalidPage(
                'That page number is too high for the current page size')

        # Force the search to evaluate and then attach the count. We want to
        # avoid an extra useless query even if there are no results, so we
        # directly fetch the count from hits.
        if self.use_elasticsearch_dsl:
            result = self.object_list[bottom:top].execute()

            # Overwrite `object_list` with the list of ES results.
            page = Page(result.hits, number, self)
            # Update the `_count`.
            self._count = page.object_list.total
        else:
            page = Page(self.object_list[bottom:top], number, self)

            # Force the search to evaluate and then attach the count.
            list(page.object_list)
            self._count = page.object_list.count()

        # Now that we have the count validate that the page number isn't higher
        # than the possible number of pages and adjust accordingly.
        if number > self.num_pages:
            if number == 1 and self.allow_empty_first_page:
                pass
            else:
                raise EmptyPage('That page contains no results')

        return page


class CustomPageNumberPagination(PageNumberPagination):
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        # Like PageNumberPagination.get_paginated_response, but with
        # 'page_size' added to the top of the response data.
        return Response(OrderedDict([
            # Note that self.page_size doesn't work, it contains the default
            # page size.
            ('page_size', self.page.paginator.per_page),
            ('count', self.page.paginator.count),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data)
        ]))


class ESPageNumberPagination(CustomPageNumberPagination):
    """Custom pagination implementation to hook in our `ESPaginator`."""
    django_paginator_class = ESPaginator


class OneOrZeroPageNumberPagination(CustomPageNumberPagination):
    """Fake pagination that returns a result object like
    CustomPageNumberPagination, but for special cases where we know we're never
    going to have more than one object in the results anyway.
    """
    def paginate_queryset(self, queryset, request, view=None):
        return list(queryset[:1])

    def get_paginated_response(self, data):
        # Always consider page_size is 1, avoid the count() call, and never
        # return next/prev links.
        return Response(OrderedDict([
            ('page_size', 1),
            ('count', len(data)),
            ('next', None),
            ('previous', None),
            ('results', data)
        ]))
