from django.core.exceptions import ValidationError as DjangoValidationError

from olympia.amo.validators import OneOrMorePrintableCharacterValidator

from rest_framework import serializers


class OneOrMorePrintableCharacterAPIValidator(
        OneOrMorePrintableCharacterValidator):
    """Like OneOrMorePrintableCharacterValidator, but for the API - raises
    a DRF ValidationError instead of a django one."""

    def __call__(self, value):
        try:
            return super(
                OneOrMorePrintableCharacterAPIValidator, self).__call__(value)
        except DjangoValidationError:
            raise serializers.ValidationError(self.message)
