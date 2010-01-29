from django.db import models

import amo.models
from translations.fields import TranslatedField


class TranslatedModel(amo.models.ModelBase):
    name = TranslatedField()
    description = TranslatedField()


class UntranslatedModel(amo.models.ModelBase):
    """Make sure nothing is broken when a model doesn't have translations."""
    number = models.IntegerField()
