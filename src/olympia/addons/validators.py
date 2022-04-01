from django import forms

from rest_framework import exceptions

from .utils import verify_mozilla_trademark


class VerifyMozillaTrademark:
    requires_context = True

    def __call__(self, value, serializer_field):
        user = serializer_field.context['request'].user
        try:
            verify_mozilla_trademark(value, user)
        except forms.ValidationError as exc:
            raise exceptions.ValidationError(exc.message)
