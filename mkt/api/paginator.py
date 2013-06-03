from rest_framework import serializers
from rest_framework import pagination
from rest_framework.templatetags.rest_framework import replace_query_param


class NextPageField(serializers.Field):
    """Wrapper to remove absolute_uri."""
    page_field = 'page'

    def to_native(self, value):
        if not value.has_next():
            return None
        page = value.next_page_number()
        request = self.context.get('request')
        url = request and request.get_full_path() or ''
        return replace_query_param(url, self.page_field, page)


class PreviousPageField(serializers.Field):
    """Wrapper to remove absolute_uri."""
    page_field = 'page'

    def to_native(self, value):
        if not value.has_previous():
            return None
        page = value.previous_page_number()
        request = self.context.get('request')
        url = request and request.get_full_path() or ''
        return replace_query_param(url, self.page_field, page)


class MetaSerializer(serializers.Serializer):
    next = NextPageField(source='*')
    prev = PreviousPageField(source='*')
    page = serializers.Field(source='number')
    total_count = serializers.Field(source='paginator.count')


class CustomPaginationSerializer(pagination.BasePaginationSerializer):
    meta = MetaSerializer(source='*')  # Takes the page object as the source
    results_field = 'objects'
