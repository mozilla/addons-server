import urlparse

from django.http import QueryDict

from rest_framework import serializers
from rest_framework import pagination


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
        query_dict = QueryDict(query).copy()
        query_dict.update(params)
        query = query_dict.urlencode()
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
