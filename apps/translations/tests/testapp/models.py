from django.db import models

import amo.models
from translations.fields import TranslatedField, PurifiedField, LinkifiedField


class TranslatedModel(amo.models.ModelBase):
    name = TranslatedField()
    description = TranslatedField()
    default_locale = models.CharField(max_length=10)
    no_locale = TranslatedField(require_locale=False)


class UntranslatedModel(amo.models.ModelBase):
    """Make sure nothing is broken when a model doesn't have translations."""
    number = models.IntegerField()


class FancyModel(amo.models.ModelBase):
    """Mix it up with purified and linkified fields."""
    purified = PurifiedField()
    linkified = LinkifiedField()
