from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import serializers

from olympia.amo.validators import OneOrMorePrintableCharacterValidator


class OneOrMorePrintableCharacterAPIValidator(OneOrMorePrintableCharacterValidator):
    """Like OneOrMorePrintableCharacterValidator, but for the API - raises
    a DRF ValidationError instead of a django one."""

    def __call__(self, value):
        try:
            return super().__call__(value)
        except DjangoValidationError:
            raise serializers.ValidationError(self.message)
