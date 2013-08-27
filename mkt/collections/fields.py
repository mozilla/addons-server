import re

from django.core import exceptions
from django.db.models.fields import CharField
from django.utils.translation import ugettext_lazy as _


class ColorField(CharField):
    """
    Model field that only accepts 7-character hexadecimal color representations,
    e.g. #FF0035.
    """
    description = _('Hexadecimal color')

    def __init__(self, *args, **kwargs):
        kwargs['max_length'] = kwargs.get('max_length', 7)
        self.default_error_messages.update({
            'bad_hex': _('Must be a valid hex color code, e.g. #FF0035.'),
        })
        super(ColorField, self).__init__(*args, **kwargs)

    def validate(self, value, model_instance):
        if value and not re.match('^\#([0-9a-fA-F]{6})$', value):
            raise exceptions.ValidationError(self.error_messages['bad_hex'])
