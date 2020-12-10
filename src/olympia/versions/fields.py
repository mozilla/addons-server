from django.db import models

from .compare import VersionString


class VersionStringFieldDescriptor:
    def __init__(self, field):
        self.field = field

    def __set__(self, instance, value):
        value = self.field.to_python(value)
        instance.__dict__[self.field.attname] = value

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return instance.__dict__.get(self.field.attname)


class VersionStringField(models.CharField):
    empty_values = [None, '']

    def __init__(self, *args, **kwargs):
        if (default := kwargs.get('default')) and not isinstance(
            default, VersionString
        ):
            kwargs['default'] = VersionString(default)
        super().__init__(*args, **kwargs)

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def to_python(self, value):
        if isinstance(value, VersionString) or value is None:
            return value
        return VersionString(value)

    def contribute_to_class(self, cls, name, private_only=False):
        super().contribute_to_class(cls, name, private_only)
        setattr(cls, self.attname, VersionStringFieldDescriptor(self))
