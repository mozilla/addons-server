from django.utils.translation import gettext

from rest_framework import serializers
from rest_framework.filters import BaseFilterBackend

from olympia.amo import ADDON_TYPE_CHOICES_API


class ModelFieldFilter(BaseFilterBackend):
    # These properties should be defined by subclasses
    reverse_dict = {}
    query_param = None
    model_field = None

    def filter_queryset(self, request, queryset, view):
        def parse_value(value):
            if value not in self.reverse_dict:
                raise serializers.ValidationError(
                    gettext('Invalid "%s" parameter.' % self.query_param)
                )
            return self.reverse_dict[value]

        if not (self.reverse_dict and self.query_param and self.model_field):
            raise NotImplementedError(
                'Subclasses of ModelFieldFilter must define reverse_dict, '
                'query_param and model_field.'
            )

        if value_string := request.GET.get(self.query_param):
            valid_values = [parse_value(value) for value in value_string.split(',')]
            return queryset.filter(**{f'{self.model_field}__in': valid_values})
        return queryset


class AddonTypeFilter(ModelFieldFilter):
    reverse_dict = {v: k for k, v in ADDON_TYPE_CHOICES_API.items()}
    query_param = 'type'
    model_field = 'type'
