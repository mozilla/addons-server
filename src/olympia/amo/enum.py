from types import DynamicClassAttribute

from django.db import models
from django.utils.functional import classproperty


class SubsetMixin:
    @classmethod
    def get_subset(cls, name, members):
        # we want to create a new [Str]EnumChoices instance, not the parent class
        subset = cls.__bases__[0](
            name,
            [(member, cls[member].value) for member in members],
        )
        for submember in subset:
            submember._label_ = cls[submember.name].label
        return subset

    @classmethod
    def add_subset(cls, name, members):
        subset = cls.get_subset(name, members)
        setattr(cls, name, subset)


class ApiValueMixin:
    @DynamicClassAttribute
    def api_value(self):
        return self.name.lower()

    @classproperty
    def api_values(cls):
        return [member.api_value for member in cls]

    @classproperty
    def api_choices(cls):
        empty = [(None, None)] if hasattr(cls, '__empty__') else []
        return empty + [(member.value, member.api_value) for member in cls]


class StrEnumChoices(SubsetMixin, ApiValueMixin, models.TextChoices):
    pass


class EnumChoices(SubsetMixin, ApiValueMixin, models.IntegerChoices):
    pass


class EnumChoicesApiDash(EnumChoices):
    """Like EnumChoices but the api_value uses dash (-) as separator
    instead of underscore (_)."""

    @DynamicClassAttribute
    def api_value(self):
        return (
            api_value.replace('_', '-')
            if (api_value := super().api_value)
            else api_value
        )

    @classmethod
    def from_api_value(cls, value):
        return cls[value.upper().replace('-', '_')] if value else cls[value]
