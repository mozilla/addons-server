from django_filters.filterset import FilterSet

from mkt.collections.models import Collection


class CollectionFilterSetWithFallback(FilterSet):
    class Meta:
        model = Collection
        fields = ['carrier', 'region', 'category']

    # Fields that can be removed when filtering the queryset if there
    # are no results for the currently applied filters, in the order
    # that they'll be removed. See `next_fallback`.
    fields_fallback_order = ('carrier', 'region', 'category')

    def next_fallback(self):
        """
        Return the next field to remove from the filters if we didn't find any
        results with the ones currently in use. It relies on
        `fields_fallback_order`.

        The `qs` property will call this method and use it to remove filters
        from `self.data` till a result is returned by the queryset or
        there are no filter left to remove.
        """
        for f in self.fields_fallback_order:
            if f in self.data:
                return f
        return None

    def __init__(self, *args, **kwargs):
        super(CollectionFilterSetWithFallback, self).__init__(*args, **kwargs)
        # Make self.data mutable for later.
        self.data = self.data.copy()

    @property
    def qs(self):
        qs = super(CollectionFilterSetWithFallback, self).qs
        next_fallback = self.next_fallback()
        if next_fallback and not qs.exists():
            # FIXME: add current filter set to API-Filter in response.
            self.data.pop(next_fallback)
            del self._form
            del self._qs
            qs = self.qs
        return qs
