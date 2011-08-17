import re

from django.forms import fields
from django.db import models
from django.core import exceptions

from tower import ugettext as _

from amo.widgets import ColorWidget


class DecimalCharField(models.DecimalField):
    """Like the standard django DecimalField but stored in a varchar

    In order to gracefully read crappy data, use nullify_invalid=True.
    This will set the field's value to None rather than raising an exception
    whenever a non-null, non-decimal string is read from a queryset.

    However, use this option with caution as it also prevents exceptions
    from being raised during model property assignment. This could allow you
    to "successfuly" save a ton of data when all that is really written
    is NULL. It might be best to combine this with the null=False option.
    """

    description = 'Decimal number stored as a varchar'
    __metaclass__ = models.SubfieldBase

    def __init__(self, verbose_name=None, name=None, max_digits=None,
            decimal_places=None, nullify_invalid=False, **kwargs):
        self.nullify_invalid = nullify_invalid
        kwargs['max_length'] = max_digits + 1
        super(DecimalCharField, self).__init__(verbose_name, name,
            max_digits=max_digits, decimal_places=decimal_places, **kwargs)

    def get_internal_type(self):
        return "CharField"

    def to_python(self, value):
        try:
            return super(DecimalCharField, self).to_python(value)
        except exceptions.ValidationError:
            if self.nullify_invalid:
                return None
            else:
                raise

    def get_db_prep_save(self, value, connection, prepared=False):
        if prepared:
            return value
        else:
            return self.get_prep_value(value)

    def get_prep_value(self, value):
        if value is None:
            return value
        return self.format_number(value)


class ColorField(fields.CharField):

    widget = ColorWidget

    def __init__(self, max_length=7, min_length=None, *args, **kwargs):
        super(ColorField, self).__init__(max_length, min_length, *args,
                                         **kwargs)

    def clean(self, value):
        super(ColorField, self).clean(value)
        if value and not re.match('^\#([0-9a-fA-F]{6})$', value):
            raise exceptions.ValidationError(
                _(u'This must be a valid hex color code, such as #000000.'))
        return value
