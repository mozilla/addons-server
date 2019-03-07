import re

from django.conf import settings
from django.core import exceptions
from django.core.validators import RegexValidator, URLValidator
from django.db import models
from django.db.models.fields import related_descriptors
from django.forms import fields
from django.utils.translation import ugettext_lazy as _
from django.utils.functional import cached_property

from nobot.fields import HumanCaptchaField, HumanCaptchaWidget


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


class ReCaptchaWidget(HumanCaptchaWidget):
    """Added to workaround to nobot0.5 not supporting django2.1"""
    def render(self, name, value, attrs=None, renderer=None):
        return super(ReCaptchaWidget, self).render(name, value, attrs=attrs)


class ReCaptchaField(HumanCaptchaField):
    # Sub-class so we can translate the strings.
    default_error_messages = {
        'captcha_invalid': _('Incorrect, please try again.'),
        'captcha_error': _('Error verifying input, please try again.'),
    }
    widget_class = ReCaptchaWidget


class ManyToManyDescriptor(related_descriptors.ManyToManyDescriptor):

    @cached_property
    def related_manager_cls(self):
        """The constrained_target optimization doesn't play nice with our
        ManagerBase that has default filtering, so set to None so it's
        bypassed."""
        manager = super(ManyToManyDescriptor, self).related_manager_cls
        setattr(manager, 'constrained_target', None)
        return manager


class ManyToManyField(models.ManyToManyField):
    def contribute_to_class(self, cls, name, **kwargs):
        super(ManyToManyField, self).contribute_to_class(cls, name, **kwargs)
        setattr(cls, self.name, ManyToManyDescriptor(
            self.remote_field, reverse=False))
