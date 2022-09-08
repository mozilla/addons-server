import re
import ipaddress

from django.conf import settings
from django.core import exceptions
from django.core.validators import RegexValidator, URLValidator
from django.db import models
from django.forms import fields
from django.utils.translation import gettext_lazy as _

from captcha.fields import ReCaptchaField as UpstreamReCaptchaField


class PositiveAutoField(models.AutoField):
    """An AutoField that's based on unsigned int instead of a signed int
    allowing twice as many positive values to be used for the primary key.

    Influenced by https://github.com/django/django/pull/8183

    Because AutoFields are special we need a custom database backend to support
    using them.  See olympia.core.db.mysql.base for that."""

    description = _('Positive integer')

    def get_internal_type(self):
        return 'PositiveAutoField'

    def rel_db_type(self, connection):
        return models.PositiveIntegerField().db_type(connection=connection)


class VarBinaryField(models.BinaryField):
    def db_type(self, connection):
        return f'varbinary({self.max_length})'


class IPAddressBinaryField(VarBinaryField):
    """This field lets us store the ip address in binary in the database - equivalent to
    INET6_ATON() in MySQL for speedy queries - and expose the value in Django as a
    IPv4Address or IPv6Address, which nicely renders as a human readable string.

    # It allows SQL queries like:
    # SELECT INET6_NTOA(`ip_address_binary`) FROM `log_activity_ip`
    # WHERE `ip_address_binary` >= INET6_ATON('127.0.0.1')
    # AND `ip_address_binary` <= INET6_ATON('127.0.0.254');
    """

    def __init__(self, *args, max_length=16, **kwargs):
        super().__init__(*args, max_length=max_length, **kwargs)

    def from_db_value(self, value, expression, connection, *args):
        return self.to_python(value)

    def to_python(self, value):
        try:
            # ip_address() is quite tolerant of arg type - it'll accept a string; a
            # bytestring - i.e. what's stored in the db; or an IPv4Address|IPv6Address.
            return ipaddress.ip_address(value) if value is not None else None
        except Exception as exc:
            raise exceptions.ValidationError(exc)

    def get_prep_value(self, value):
        return self.to_python(value).packed if value is not None else None

    def value_to_string(self, obj):
        return str(self.value_from_object(obj))


class HttpHttpsOnlyURLField(fields.URLField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.validators = [
            URLValidator(schemes=('http', 'https')),
            # Reject AMO URLs, see:
            # https://github.com/mozilla/addons-server/issues/9012
            RegexValidator(
                regex=r'%s' % re.escape(settings.DOMAIN),
                message=_(
                    'This field can only be used to link to external websites.'
                    ' URLs on %(domain)s are not allowed.',
                )
                % {'domain': settings.DOMAIN},
                code='no_amo_url',
                inverse_match=True,
            ),
        ]


class ReCaptchaField(UpstreamReCaptchaField):
    # Sub-class so we can translate the strings.
    default_error_messages = {
        'captcha_invalid': _('Incorrect, please try again.'),
        'captcha_error': _('Error verifying input, please try again.'),
    }


def validate_cidr(value):
    try:
        ipaddress.ip_network(value)
    except ValueError:
        raise exceptions.ValidationError(
            _('Enter a valid IP4 or IP6 network.'), code='invalid'
        )


class CIDRField(models.Field):
    empty_strings_allowed = False
    description = _('CIDR')
    default_error_messages = {'invalid': _('Enter a valid IP4 or IP6 network.')}

    def __init__(self, verbose_name=None, name=None, *args, **kwargs):
        self.validators = [validate_cidr]
        kwargs['max_length'] = 45
        super().__init__(verbose_name, name, *args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        del kwargs['max_length']
        return name, path, args, kwargs

    def db_type(self, connection):
        return 'char(45)'

    def from_db_value(self, value, expression, connection, *args):
        return self.to_python(value)

    def to_python(self, value):
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()

        try:
            return ipaddress.ip_network(value)
        except Exception as exc:
            raise exceptions.ValidationError(exc)

    def get_prep_lookup(self, lookup_type, value):
        if lookup_type == 'exact':
            return self.get_prep_value(value)
        elif lookup_type == 'in':
            return [self.get_prep_value(v) for v in value]
        else:
            raise TypeError(f'Lookup type {lookup_type} not supported.')

    def get_prep_value(self, value):
        return str(value)

    def formfield(self, **kwargs):
        defaults = {'form_class': fields.CharField, 'validators': self.validators}
        defaults.update(kwargs)
        return super().formfield(**defaults)
