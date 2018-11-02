import re

from django.conf import settings
from django.core import exceptions
from django.core.validators import RegexValidator, URLValidator
from django.db import models
from django.forms import fields
from django.utils.translation import ugettext, ugettext_lazy as _

from nobot.fields import HumanCaptchaField

from olympia.amo.widgets import ColorWidget


class PositiveAutoField(models.AutoField):
    """An AutoField that's based on unsigned int instead of a signed int
    allowing twice as many positive values to be used for the primary key.

    Influenced by https://github.com/django/django/pull/8183

    Because AutoFields are special we need a custom database backend to support
    using them.  See olympia.core.db.mysql.base for that."""
    description = _("Positive integer")

    def get_internal_type(self):
        return "PositiveAutoField"

    def rel_db_type(self, connection):
        return models.PositiveIntegerField().db_type(connection=connection)


class URLValidatorBackport(URLValidator):
    def __call__(self, value):
        # stupid backport of https://github.com/django/django/commit/a9e188
        try:
            return super(URLValidatorBackport, self).__call__(value)
        except ValueError:
            raise exceptions.ValidationError(self.message, code=self.code)


class HttpHttpsOnlyURLField(fields.URLField):

    def __init__(self, *args, **kwargs):
        super(HttpHttpsOnlyURLField, self).__init__(*args, **kwargs)

        self.validators = [
            URLValidatorBackport(schemes=('http', 'https')),
            # Reject AMO URLs, see:
            # https://github.com/mozilla/addons-server/issues/9012
            RegexValidator(
                regex=r'%s' % re.escape(settings.DOMAIN),
                message=_(
                    'This field can only be used to link to external websites.'
                    ' URLs on %(domain)s are not allowed.',
                ) % {'domain': settings.DOMAIN},
                code='no_amo_url',
                inverse_match=True
            )
        ]


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
        if value and not re.match(r'^\#([0-9a-fA-F]{6})$', value):
            raise exceptions.ValidationError(ugettext(
                u'This must be a valid hex color code, such as #000000.'))
        return value
