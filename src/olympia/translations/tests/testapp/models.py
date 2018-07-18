from django.db import models

from olympia.amo.models import ManagerBase, ModelBase
from olympia.translations.fields import (
    LinkifiedField,
    PurifiedField,
    TranslatedField,
    save_signal,
)


class TranslatedModel(ModelBase):
    name = TranslatedField()
    description = TranslatedField()
    default_locale = models.CharField(max_length=10)
    no_locale = TranslatedField(require_locale=False)

    translated_through_fk = models.ForeignKey(
        'TranslatedModelLinkedAsForeignKey', null=True, default=None
    )
    objects = ManagerBase()


models.signals.pre_save.connect(
    save_signal, sender=TranslatedModel, dispatch_uid='testapp_translatedmodel'
)


class UntranslatedModel(ModelBase):
    """Make sure nothing is broken when a model doesn't have translations."""

    number = models.IntegerField()


class FancyModel(ModelBase):
    """Mix it up with purified and linkified fields."""

    purified = PurifiedField()
    linkified = LinkifiedField()


models.signals.pre_save.connect(
    save_signal, sender=FancyModel, dispatch_uid='testapp_fancymodel'
)


class TranslatedModelWithDefaultNull(ModelBase):
    name = TranslatedField(default=None)

    objects = ManagerBase()


class TranslatedModelLinkedAsForeignKey(ModelBase):
    name = TranslatedField()


models.signals.pre_save.connect(
    save_signal,
    sender=TranslatedModelLinkedAsForeignKey,
    dispatch_uid='testapp_translatedmodellinkedasforeignkey_translations',
)


models.signals.pre_save.connect(
    save_signal,
    sender=TranslatedModelWithDefaultNull,
    dispatch_uid='testapp_translatedmodelwithdefaultnull',
)
