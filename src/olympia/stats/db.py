import json

from django.db import models


class StatsDictField(models.TextField):

    description = 'A dictionary of counts stored as serialized json.'
    __metaclass__ = models.SubfieldBase

    def db_type(self, connection):
        return 'text'

    def to_python(self, value):
        # object case
        if value is None:
            return None
        if isinstance(value, dict):
            return value

        try:
            data = json.loads(value)
        except ValueError:
            data = None
        return data

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


class LargeStatsDictField(StatsDictField):

    description = 'Same as StatsDictField with a MEDIUMTEXT MySQL field.'

    def db_type(self, connection):
        return 'mediumtext'
