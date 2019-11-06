from collections import OrderedDict

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from olympia.amo.pagination import ESPaginator


class CustomPageNumberPagination(PageNumberPagination):
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        # Like PageNumberPagination.get_paginated_response, but with
        # 'page_size' added to the top of the response data.
        return Response(
            OrderedDict(
                [
                    # Note that self.page_size doesn't work, it contains the
                    # default page size.
                    ('page_size', self.page.paginator.per_page),
                    ('page_count', self.page.paginator.num_pages),
                    ('count', self.page.paginator.count),
                    ('next', self.get_next_link()),
                    ('previous', self.get_previous_link()),
                    ('results', data),
                ]
            )
        )


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
        return Response(
            OrderedDict(
                [
                    ('page_size', 1),
                    ('page_count', 1),
                    ('count', len(data)),
                    ('next', None),
                    ('previous', None),
                    ('results', data),
                ]
            )
        )
