import unicodedata

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _

from rest_framework import fields


@deconstructible
class OneOrMorePrintableCharacterValidator:
    """Validate that the value contains at least one printable character."""

    message = _('Must contain at least one printable character.')
    # See http://www.unicode.org/reports/tr4/tr44-6.html#Property_Values
    # This is relatively permissive, we want at least one printable character,
    # but we allow it to be punctuation or symbol. So we want either a
    # (L)etter, (N)umber, (P)unctuation, or (S)ymbol
    # (Not (M)ark, (C)ontrol or (Z)-spaces/separators)
    unicode_categories = ('L', 'N', 'P', 'S')

    def __call__(self, value):
        for character in value:
            if unicodedata.category(character)[0] in self.unicode_categories:
                return
        raise ValidationError(self.message)


@deconstructible
class OneOrMoreLetterOrNumberCharacterValidator(OneOrMorePrintableCharacterValidator):
    """Validate that the value contains at least a letter or a number
    character."""

    message = _('Ensure this field contains at least one letter or number character.')

    # We want at least a (L)etter or (N)umber for the value to be valid.
    unicode_categories = ('L', 'N')


class CreateOnlyValidator:
    """
    This validator just raises SkipField when the field is used for update operations.
    """

    requires_context = True

    def __call__(self, value, serializer_field):
        if serializer_field.parent.instance is not None:
            raise fields.SkipField()


class PreventPartialUpdateValidator:
    """
    This validator raises SkipField if the field is used in a partial=True
    (partial_update / PATCH) serializer instance.
    """

    requires_context = True

    def __call__(self, value, serializer_field):
        if serializer_field.parent.partial:
            raise fields.SkipField()
