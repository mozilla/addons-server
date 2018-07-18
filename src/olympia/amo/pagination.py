from math import ceil

from django.conf import settings
from django.core.paginator import (
    EmptyPage,
    InvalidPage,
    Page,
    PageNotAnInteger,
    Paginator,
)
from django.utils.functional import cached_property


class ESPaginator(Paginator):
    """
    A better paginator for search results
    The normal Paginator does a .count() query and then a slice. Since ES
    results contain the total number of results, we can take an optimistic
    slice and then adjust the count.

    :param use_elasticsearch_dsl:
        Used to activate support for our elasticsearch-dsl based pagination
        implementation. elasticsearch-dsl is being used in the v3+ API while
        we have our own wrapper implementation in :mod:`olympia.amo.search`.
    """

    # Maximum result position. Should match 'index.max_result_window' ES
    # setting if present. ES defaults to 10000 but we'd like more to make sure
    # all our extensions can be found if searching without a query and
    # paginating through all results.
    max_result_window = settings.ES_MAX_RESULT_WINDOW

    def __init__(self, *args, **kwargs):
        self.use_elasticsearch_dsl = kwargs.pop('use_elasticsearch_dsl', True)
        Paginator.__init__(self, *args, **kwargs)

    @cached_property
    def num_pages(self):
        """
        Returns the total number of pages.
        """
        if self.count == 0 and not self.allow_empty_first_page:
            return 0

        # Make sure we never return a page beyond max_result_window
        hits = min(self.max_result_window, max(1, self.count - self.orphans))
        return int(ceil(hits / float(self.per_page)))

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

        if top > self.max_result_window:
            raise InvalidPage(
                'That page number is too high for the current page size'
            )

        # Force the search to evaluate and then attach the count. We want to
        # avoid an extra useless query even if there are no results, so we
        # directly fetch the count from hits.
        if self.use_elasticsearch_dsl:
            result = self.object_list[bottom:top].execute()

            # Overwrite `object_list` with the list of ES results.
            page = Page(result.hits, number, self)

            # Overwrite the `count` with the total received from ES results.
            self.count = page.object_list.total
        else:
            page = Page(self.object_list[bottom:top], number, self)

            # Force the search to evaluate and then attach the count.
            list(page.object_list)
            self.count = page.object_list.count()

        # Now that we have the count validate that the page number isn't higher
        # than the possible number of pages and adjust accordingly.
        if number > self.num_pages:
            if number == 1 and self.allow_empty_first_page:
                pass
            else:
                raise EmptyPage('That page contains no results')

        return page
