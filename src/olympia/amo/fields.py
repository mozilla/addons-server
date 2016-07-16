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
