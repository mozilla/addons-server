from django.db import models

from olympia.amo.models import UncachedManagerBase, UncachedModelBase
from olympia.translations.fields import (
    LinkifiedField, PurifiedField, TranslatedField, save_signal)


class TranslatedModel(UncachedModelBase):
    name = TranslatedField()
    description = TranslatedField()
    default_locale = models.CharField(max_length=10)
    no_locale = TranslatedField(require_locale=False)

    objects = UncachedManagerBase()


models.signals.pre_save.connect(save_signal, sender=TranslatedModel,
                                dispatch_uid='testapp_translatedmodel')


class UntranslatedModel(UncachedModelBase):
    """Make sure nothing is broken when a model doesn't have translations."""
    number = models.IntegerField()


class FancyModel(UncachedModelBase):
    """Mix it up with purified and linkified fields."""
    purified = PurifiedField()
    linkified = LinkifiedField()


models.signals.pre_save.connect(save_signal, sender=FancyModel,
                                dispatch_uid='testapp_fancymodel')
