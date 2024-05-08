from django.conf import settings

from extended_choices import Choices
from extended_choices.helpers import ChoiceAttributeMixin, ChoiceEntry


def is_gate_active(request, name):
    """Check if a specific gate is active for the current API version.
    Note that `request` has to be a :class:`~rest_framework.request.Request`
    object that has `version` attached.
    We're not examining Django request objects.
    """
    gates = settings.DRF_API_GATES.get(getattr(request, 'version', None), None)
    if not gates:
        return False

    return name in gates


class DashSeperatorConvertor:
    separator = '-'

    @classmethod
    def to_slug(cls, value):
        return value.lower().replace('_', cls.separator) if value else value

    @classmethod
    def from_slug(cls, slug):
        return slug.upper().replace(cls.separator, '_') if slug else slug


class UnderscoreSeperatorConvertor:
    """The seperator is already an underscore so this is optimized to not replace"""

    @classmethod
    def to_slug(cls, value):
        return value.lower() if value else value

    @classmethod
    def from_slug(cls, slug):
        return slug.upper() if slug else slug


class APIChoiceAttributeMixin(ChoiceAttributeMixin):
    @property
    def api_value(self):
        """Property that returns the ``api_value`` attribute of the attached
        ``APIChoiceEntry``."""
        return self.choice_entry.api_value


class APIChoiceEntry(ChoiceEntry):
    convertor = UnderscoreSeperatorConvertor
    ChoiceAttributeMixin = APIChoiceAttributeMixin

    @property
    def api_value(self):
        return self.convertor.to_slug(self.constant)


class APIChoices(Choices):
    """Like a regular extended_choices.Choices class, with an extra api_choices
    property that exposes constants in lower-case, meant to be used as choices
    in an API."""

    ChoiceEntryClass = APIChoiceEntry
    convertor = ChoiceEntryClass.convertor

    @property
    def api_choices(self):
        return tuple(
            (entry[1], self.convertor.to_slug(entry[0])) for entry in self.entries
        )

    def has_api_value(self, value):
        return self.has_constant(self.convertor.from_slug(value))

    def for_api_value(self, value):
        return self.for_constant(self.convertor.from_slug(value))


class APIChoiceWithDashEntry(APIChoiceEntry):
    convertor = DashSeperatorConvertor


class APIChoicesWithDash(APIChoices):
    ChoiceEntryClass = APIChoiceWithDashEntry
    convertor = ChoiceEntryClass.convertor


class APIChoicesWithNone(APIChoices):
    """Like APIChoices, but also returns 'None' as a valid choice for `choices`
    and `api_choices` properties."""

    @property
    def choices(self):
        return ((None, 'None'),) + super().choices

    @property
    def api_choices(self):
        return ((None, None),) + super().api_choices
