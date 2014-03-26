from django.db import models

import amo.models
from translations.fields import (LinkifiedField, PurifiedField, save_signal,
                                 TranslatedField)


class TranslatedModel(amo.models.ModelBase):
    name = TranslatedField()
    description = TranslatedField()
    default_locale = models.CharField(max_length=10)
    no_locale = TranslatedField()

models.signals.pre_save.connect(save_signal, sender=TranslatedModel,
                                dispatch_uid='testapp_translatedmodel')


class UntranslatedModel(amo.models.ModelBase):
    """Make sure nothing is broken when a model doesn't have translations."""
    number = models.IntegerField()


class FancyModel(amo.models.ModelBase):
    """Mix it up with purified and linkified fields."""
    purified = PurifiedField()
    linkified = LinkifiedField()


models.signals.pre_save.connect(save_signal, sender=FancyModel,
                                dispatch_uid='testapp_fancymodel')
