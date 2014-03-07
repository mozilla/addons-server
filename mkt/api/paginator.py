import urlparse

from django.core.paginator import EmptyPage, Page, PageNotAnInteger, Paginator
from django.http import QueryDict
from django.utils.http import urlencode

from rest_framework import pagination, serializers


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
        page = Page(self.object_list[bottom:top], number, self)

        # Force the search to evaluate and then attach the count. We want to
        # avoid an extra useless query even if there are no results, so we
        # directly fetch the count from _results_cache instead of calling
        # page.object_list.count().
        # FIXME: replace by simply calling page.object_list.count() when
        # https://github.com/mozilla/elasticutils/pull/212 is merged and
        # released.
        page.object_list.execute()
        self._count = page.object_list._results_cache.count

        return page


class MetaSerializer(serializers.Serializer):
    """
    Serializer for the 'meta' dict holding pagination info that allows to stay
    backwards-compatible with the way tastypie does pagination (using offsets
    instead of page numbers), while still using a "standard" Paginator class.
    """
    next = serializers.SerializerMethodField('get_next')
    previous = serializers.SerializerMethodField('get_previous')
    total_count = serializers.SerializerMethodField('get_total_count')
    offset = serializers.SerializerMethodField('get_offset')
    limit = serializers.SerializerMethodField('get_limit')

    def replace_query_params(self, url, params):
        (scheme, netloc, path, query, fragment) = urlparse.urlsplit(url)
        query_dict = QueryDict(query).dict()
        query_dict.update(params)
        query = urlencode(query_dict)
        return urlparse.urlunsplit((scheme, netloc, path, query, fragment))

    def get_offset_link_for_page(self, page, number):
        request = self.context.get('request')
        url = request and request.get_full_path() or ''
        number = number - 1  # Pages are 1-based, but offsets are 0-based.
        per_page = page.paginator.per_page
        return self.replace_query_params(url, {'offset': number * per_page,
                                               'limit': per_page})

    def get_next(self, page):
        if not page.has_next():
            return None
        return self.get_offset_link_for_page(page, page.next_page_number())

    def get_previous(self, page):
        if not page.has_previous():
            return None
        return self.get_offset_link_for_page(page, page.previous_page_number())

    def get_total_count(self, page):
        return page.paginator.count

    def get_offset(self, page):
        index = page.start_index()
        if index > 0:
            # start_index() is 1-based, and we want a 0-based offset, so we
            # need to remove 1, unless it's already 0.
            return index - 1
        return index

    def get_limit(self, page):
        return page.paginator.per_page


class CustomPaginationSerializer(pagination.BasePaginationSerializer):
    meta = MetaSerializer(source='*')  # Takes the page object as the source
    results_field = 'objects'
