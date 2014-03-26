from django.db import models

import phpserialize as php
import json


class StatsDictField(models.TextField):

    description = 'A dictionary of counts stored as serialized php.'
    __metaclass__ = models.SubfieldBase

    def db_type(self, connection):
        return 'text'

    def to_python(self, value):
        # object case
        if value is None:
            return None
        if isinstance(value, dict):
            return value

        # string case
        if value and value[0] in '[{':
            # JSON
            try:
                d = json.loads(value)
            except ValueError:
                d = None
        else:
            # phpserialize data
            try:
                if isinstance(value, unicode):
                    value = value.encode('utf8')
                d = php.unserialize(value, decode_strings=True)
            except ValueError:
                d = None
        if isinstance(d, dict):
            return d
        return None

    def get_db_prep_value(self, value, connection, prepared=False):
        if value is None or value == '':
            return value
        try:
            value = json.dumps(dict(value))
        except TypeError:
            value = None
        return value

    def value_to_string(self, obj):
        return str(obj)
