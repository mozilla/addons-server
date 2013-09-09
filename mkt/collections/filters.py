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
            # FIXME: being able to return self.form.errors would greatly help
            # debugging.
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
    """
    FilterSet with a fallback mechanism, dropping filters in a certain order
    if no results are found.
    """

    # Combinations of fields to try, in order, when no results are found.
    fields_fallback_order = (
        ('carrier', 'cat'),
        ('region', 'cat'),
        ('cat',)
    )

    def next_fallback(self):
        """
        Yield the next set of filters to try to use.

        When we are using this FilterSet, we really want to return something,
        even if it's less relevant to the original query. When the `qs`
        property is evaluated, if no results are found, it will call this
        method to change the filters used in order to find something.
        """
        for f in self.fields_fallback_order:
            yield f

    def refilter_queryset(self):
        """
        Reset self.data with the next fields tuple to use according to the
        `fallback` generator. Then recall the `qs` property and return it.

        Can raise StopIteration if the fallback generator is exhausted.
        """
        new_fields = next(self.fallback)
        data = dict((field, self.original_data[field]) for field in new_fields
                    if field in self.original_data)
        self.data = data
        del self._form
        return self.qs

    def __init__(self, *args, **kwargs):
        super(CollectionFilterSetWithFallback, self).__init__(*args, **kwargs)
        self.original_data = self.data.copy()
        self.fallback = self.next_fallback()

    @property
    def qs(self):
        if hasattr(self, '_qs'):
            return self._qs

        qs = self.get_queryset()
        if not qs.exists():
            # FIXME: add current filter set to API-Filter in response. It
            # should be possible to implement using <filtersetinstance>.data.
            try:
                qs = self.refilter_queryset()
            except StopIteration:
                pass
        self._qs = qs
        return self._qs

