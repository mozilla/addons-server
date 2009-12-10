from django.db import models

import amo
from translations.fields import TranslatedField


class TranslatedModel(amo.ModelBase):
    name = TranslatedField()
    description = TranslatedField()


class UntranslatedModel(amo.ModelBase):
    """Make sure nothing is broken when a model doesn't have translations."""
    number = models.IntegerField()
