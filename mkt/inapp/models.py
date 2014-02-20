from django.db import models

from amo.models import ModelBase
from apps.translations.fields import save_signal, TranslatedField


class InAppProduct(ModelBase):
    """
    An item which is purchaseable from within a marketplace app.
    """
    webapp = models.ForeignKey('webapps.WebApp')
    price = models.ForeignKey('market.Price')
    name = TranslatedField(require_locale=False)
    logo_url = models.URLField(max_length=1024)

    class Meta:
        db_table = 'inapp_products'

    def __unicode__(self):
        return u'%s: %s' % (self.webapp.name, self.name)


models.signals.pre_save.connect(save_signal, sender=InAppProduct,
                                dispatch_uid='inapp_products_translations')
