from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from django.core.paginator import (
    EmptyPage, Page, PageNotAnInteger, Paginator, InvalidPage)


class ESPaginator(Paginator):
    """
    A better paginator for search results
    The normal Paginator does a .count() query and then a slice. Since ES
    results contain the total number of results, we can take an optimistic
    slice and then adjust the count.
    """
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

        # Force the search to evaluate and then attach the count. We want to
        # avoid an extra useless query even if there are no results, so we
        # directly fetch the count from hits.
        # Overwrite `object_list` with the list of ES results.
        result = self.object_list[bottom:top].execute()
        page = Page(result.hits, number, self)
        # Update the `_count`.
        self._count = page.object_list.total

        # Now that we have the count validate that the page number isn't higher
        # than the possible number of pages and adjust accordingly.
        if number > self.num_pages:
            if number == 1 and self.allow_empty_first_page:
                pass
            else:
                raise EmptyPage('That page contains no results')

        return page


class CustomPageNumberPagination(PageNumberPagination):
    """Custom pagination implementation to hook in our `ESPaginator`."""
    page_size_query_param = 'page_size'

    def paginate_queryset(self, queryset, request, view=None):
        """
        Paginate a queryset if required, either returning a
        page object, or `None` if pagination is not configured for this view.
        """
        page_size = self.get_page_size(request)
        if not page_size:
            return None

        paginator = ESPaginator(queryset, page_size)
        page_number = request.query_params.get(self.page_query_param, 1)
        if page_number in self.last_page_strings:
            page_number = paginator.num_pages

        try:
            self.page = paginator.page(page_number)
        except InvalidPage as exc:
            msg = self.invalid_page_message.format(
                page_number=page_number, message=six.text_type(exc))
            raise NotFound(msg)

        if paginator.num_pages > 1 and self.template is not None:
            # The browsable API should display pagination controls.
            self.display_page_controls = True

        self.request = request
        return list(self.page)
