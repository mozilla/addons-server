from collections import OrderedDict

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.exceptions import NotFound
from django.utils.translation import ugettext_lazy as _
from django.core.paginator import InvalidPage

from olympia.amo.pagination import ESPaginator, MaxPageReached


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
    max_allowed_page_message = _('Maximum allowed page reached.')

    def paginate_queryset(self, queryset, request, view=None):
        """
        Paginate a queryset if required, either returning a
        page object, or `None` if pagination is not configured for this view.

        Overwritten to hook in a better error message for exceeding
        `max_window_size`.
        """
        page_size = self.get_page_size(request)
        if not page_size:
            return None

        paginator = self.django_paginator_class(queryset, page_size)
        page_number = request.query_params.get(self.page_query_param, 1)
        if page_number in self.last_page_strings:
            page_number = paginator.num_pages

        try:
            self.page = paginator.page(page_number)
        except MaxPageReached as exc:
            raise NotFound(self.max_allowed_page_message)
        except InvalidPage as exc:
            msg = self.invalid_page_message.format(
                page_number=page_number, message=unicode(exc)
            )
            raise NotFound(msg)

        self.request = request
        return list(self.page)


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
