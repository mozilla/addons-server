from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import exceptions

from olympia.amo.utils import verify_no_urls
from olympia.amo.validators import OneOrMoreLetterOrNumberCharacterValidator


class OneOrMoreLetterOrNumberCharacterAPIValidator(
    OneOrMoreLetterOrNumberCharacterValidator
):
    """Like OneOrMoreLetterOrNumberCharacterValidator, but for the API - raises
    a DRF ValidationError instead of a django one."""

    def __call__(self, value):
        try:
            return super().__call__(value)
        except DjangoValidationError as exc:
            raise exceptions.ValidationError(self.message) from exc


class NoURLsValidator:
    def __call__(self, value):
        try:
            verify_no_urls(value)
        except DjangoValidationError as exc:
            raise exceptions.ValidationError(exc.message) from exc
