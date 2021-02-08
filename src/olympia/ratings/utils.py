from rest_framework import serializers
from rest_framework.exceptions import ParseError

from .models import GroupedRating


def get_grouped_ratings(request, addon):
    if 'show_grouped_ratings' in request.GET:
        try:
            show_grouped_ratings = serializers.BooleanField().to_internal_value(
                request.GET['show_grouped_ratings']
            )
        except serializers.ValidationError:
            raise ParseError('show_grouped_ratings parameter should be a boolean')
        if show_grouped_ratings and addon:
            return dict(GroupedRating.get(addon.id))
