from rest_framework.filters import OrderingFilter


class OrderingAliasFilter(OrderingFilter):
    """Overload the standard OrderingFilter filter with support for having more
    friendly sort parameters.

    Configure by setting ordering_field_aliases = {'alias': 'field', ...} on
    your view."""

    def remove_invalid_fields(self, queryset, fields, view, request):
        aliases = getattr(view, 'ordering_field_aliases', {})
        # Add to view.ordering_fields
        view.ordering_fields = getattr(view, 'ordering_fields', ()) + tuple(
            aliases.values()
        )
        # Account for desc and asc sorting
        aliases.update(
            {
                '-%s' % alias: '-%s' % field
                for (alias, field) in aliases.items()
            }
        )
        # Replace field aliases with their actual field names.
        fields = [aliases.get(field, field) for field in fields]
        out = super(OrderingAliasFilter, self).remove_invalid_fields(
            queryset, fields, view, request
        )
        return out
