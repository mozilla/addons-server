import re

from django.core import exceptions
from django.db import models
from django.forms import fields

from tower import ugettext as _
from nobot.fields import HumanCaptchaField

from olympia.amo.widgets import ColorWidget


class ReCaptchaField(HumanCaptchaField):
    # Sub-class so we can translate the strings.
    default_error_messages = {
        'captcha_invalid': _('Incorrect, please try again.'),
        'captcha_error': _('Error verifying input, please try again.'),
    }


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
        super(DecimalCharField, self).__init__(
            verbose_name, name, max_digits=max_digits,
            decimal_places=decimal_places, **kwargs)

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


class SeparatedValuesField(fields.Field):
    """
    Field that allows the given base field to accept multiple values using
    the given separator.

    E.g.::

        >>> field = SeparatedValuesField(forms.EmailField)
        >>> field.clean(u'a@b.com,,   \n,c@d.com')
        u'a@b.com, c@d.com'

    """

    def __init__(self, base_field, separator=None, *args, **kwargs):
        super(SeparatedValuesField, self).__init__(*args, **kwargs)
        self.base_field = base_field
        self.separator = separator or ','

    def clean(self, data):
        if not data:
            if self.required:
                raise exceptions.ValidationError(
                    _(u'Enter at least one value.'))
            else:
                return None

        value_list = filter(None, map(unicode.strip,
                                      data.split(self.separator)))

        self.value_list = []
        base_field = self.base_field()
        for value in value_list:
            if value:
                self.value_list.append(base_field.clean(value))

        return u', '.join(self.value_list)
