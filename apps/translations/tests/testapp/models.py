from django.db import models

import amo.models
from translations.fields import TranslatedField


class TranslatedModel(amo.models.ModelBase):
    name = TranslatedField()
    description = TranslatedField()
    default_locale = models.CharField(max_length=10)


class UntranslatedModel(amo.models.ModelBase):
    """Make sure nothing is broken when a model doesn't have translations."""
    number = models.IntegerField()
