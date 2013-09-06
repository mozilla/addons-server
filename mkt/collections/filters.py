from django import forms
from django.core.validators import EMPTY_VALUES
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
        # Create a choice dynamically to allow None, slugs and ids.
        slugs_choices = self.choices_dict.items()
        ids_choices = [(v.id, v) for v in self.choices_dict.values()]
        kwargs['choices'] = [(None, None)] + slugs_choices + ids_choices

        return super(SlugChoiceFilter, self).__init__(*args, **kwargs)

    def filter(self, qs, value):
        if value == '' or value is None:
            return qs.filter(**{'%s__isnull' % self.name: True})
        else:
            if not value.isdigit():
                # We are passed a slug, get the id by looking at the choices
                # dict, and use that when filtering the queryset.
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

    def filter(self, qs, value):
        return qs.filter(**{'%s__%s' % (self.name, self.lookup_type): value})


class CollectionFilterSet(FilterSet):
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

    def get_queryset(self):
        """
        Return the queryset to use for the filterset.

        Copied from django-filter qs property, modified to support filtering on
        'empty' values, at the expense of multi-lookups like 'x < 4 and x > 2'.
        """
        valid = self.is_bound and self.form.is_valid()

        if self.strict and self.is_bound and not valid:
            return self.queryset.none()

        # Start with all the results and filter from there.
        qs = self.queryset.all()
        for name, filter_ in self.filters.items():
            if valid:
                if name in self.form.data:
                    value = self.form.cleaned_data[name]
                else:
                    continue
            else:
                raw_value = self.form[name].value()
                try:
                    value = self.form.fields[name].clean(raw_value)
                except forms.ValidationError:
                    if self.strict:
                        return self.queryset.none()
                    else:
                        continue

            # At this point we should have valid & clean data.
            qs = filter_.filter(qs, value)

        # Optional ordering.
        if self._meta.order_by:
            order_field = self.form.fields[self.order_by_field]
            data = self.form[self.order_by_field].data
            ordered = None
            try:
                ordered = order_field.clean(data)
            except forms.ValidationError:
                pass

            if ordered in EMPTY_VALUES and self.strict:
                ordered = self.form.fields[self.order_by_field].choices[0][0]

            if ordered:
                qs = qs.order_by(*self.get_order_by(ordered))

        return qs

    @property
    def qs(self):
        if hasattr(self, '_qs'):
            return self._qs
        self._qs = self.get_queryset()
        return self._qs


class CollectionFilterSetWithFallback(CollectionFilterSet):
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
        if hasattr(self, '_qs'):
            return self._qs

        qs = self.get_queryset()
        # FIXME: being able to return self.form.errors would greatly help
        # debugging.
        next_fallback = self.next_fallback()

        if next_fallback and not qs.exists():
            # FIXME: add current filter set to API-Filter in response. It
            # should be possible to implement using <filtersetinstance>.data.
            self.data.pop(next_fallback)
            del self._form
            qs = self.qs

        self._qs = qs
        return self._qs

