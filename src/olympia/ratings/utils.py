from rest_framework import serializers
from rest_framework.exceptions import ParseError

from .models import RatingAggregate


def get_grouped_ratings(request, addon):
    if 'show_grouped_ratings' in request.GET:
        try:
            show_grouped_ratings = serializers.BooleanField().to_internal_value(
                request.GET['show_grouped_ratings']
            )
        except serializers.ValidationError as exc:
            raise ParseError(
                'show_grouped_ratings parameter should be a boolean'
            ) from exc
        if show_grouped_ratings and addon:
            try:
                aggregate = addon.ratingaggregate
            except RatingAggregate.DoesNotExist:
                aggregate = RatingAggregate()
            return {idx: getattr(aggregate, f'count_{idx}') for idx in range(1, 6)}
