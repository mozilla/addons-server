import re

from django.core import exceptions
from django.core.validators import URLValidator
from django.forms import fields
from django.utils.translation import ugettext as _

from nobot.fields import HumanCaptchaField

from olympia.amo.widgets import ColorWidget


class URLValidatorBackport(URLValidator):
    def __call__(self, value):
        # stupid backport of https://github.com/django/django/commit/a9e188
        try:
            return super(URLValidatorBackport, self).__call__(value)
        except ValueError:
            raise exceptions.ValidationError(self.message, code=self.code)


class HttpHttpsOnlyURLField(fields.URLField):
    default_validators = [URLValidatorBackport(schemes=('http', 'https'))]


class ReCaptchaField(HumanCaptchaField):
    # Sub-class so we can translate the strings.
    default_error_messages = {
        'captcha_invalid': _('Incorrect, please try again.'),
        'captcha_error': _('Error verifying input, please try again.'),
    }


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
