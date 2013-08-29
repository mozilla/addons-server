from django.db.models import Q

from django_filters.filters import ChoiceFilter, ModelChoiceFilter
from django_filters.filterset import FilterSet

import amo
import mkt
from addons.models import Category
from mkt.api.forms import SluggableModelChoiceField
from mkt.collections.models import Collection


class SlugChoiceFilter(ChoiceFilter):
    def __init__(self, *args, **kwargs):
        self.choices_dict = kwargs.pop('choices_dict')
        kwargs['choices'] = self.choices_dict.items()
        return super(SlugChoiceFilter, self).__init__(*args, **kwargs)

    def filter(self, qs, value):
        if not value:
            # Filters are called everytime, even when there was no data given,
            # and we don't want to do the slug match and NULL values filtering
            # in that case, so just use django-filter implementation if value
            # is falsy.
            return super(SlugChoiceFilter, self).filter(qs, value)
        else:
            # We are passed a slug, get the id by looking at the choices dict,
            # and use that when filtering the queryset.
            value = self.choices_dict.get(value, None)
            if value is not None:
                value = value.id

            # Do the filtering, adding a OR to catch NULL values as well.
            return qs.filter(
                Q(**{self.name: value}) |
                Q(**{'%s__isnull' % self.name: True})
            )


class SlugModelChoiceFilter(ModelChoiceFilter):
    field_class = SluggableModelChoiceField


class CollectionFilterSetWithFallback(FilterSet):
    # Note: the filter names must match what ApiSearchForm and CategoryViewSet
    # are using.
    carrier = SlugChoiceFilter(name='carrier',
        choices_dict=mkt.carriers.CARRIER_MAP)
    region = SlugChoiceFilter(name='region',
        choices_dict=mkt.regions.REGIONS_DICT)
    cat = SlugModelChoiceFilter(name='category',
        queryset=Category.objects.filter(type=amo.ADDON_WEBAPP),
        sluggable_to_field_name='slug',)

    class Meta:
        model = Collection
        # All fields are provided above, but django-filter needs Meta.field to
        # exist.
        fields = []

    # Fields that can be removed when filtering the queryset if there
    # are no results for the currently applied filters, in the order
    # that they'll be removed. See `next_fallback`.
    fields_fallback_order = ('carrier', 'region', 'cat')

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
        # FIXME: being able to return self.form.errors would greatly help
        # debugging.
        next_fallback = self.next_fallback()

        if next_fallback and not qs.exists():
            # FIXME: add current filter set to API-Filter in response. It
            # should be possible to implement using <filtersetinstance>.data.
            self.data.pop(next_fallback)
            del self._form
            del self._qs
            qs = self.qs
        return qs
