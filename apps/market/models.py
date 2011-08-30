# -*- coding: utf-8 -*-
import time

from django.conf import settings
from django.db import models
from django.dispatch import receiver

from translations.fields import TranslatedField

import amo
import amo.models
from amo.urlresolvers import reverse
from stats.models import Contribution
from users.models import UserProfile

import commonware.log
from jinja2.filters import do_dictsort
import jwt


log = commonware.log.getLogger('z.market')


class PriceManager(amo.models.ManagerBase):

    def active(self):
        return self.filter(active=True)


class Price(amo.models.ModelBase):
    active = models.BooleanField(default=True)
    name = TranslatedField()
    price = models.DecimalField(max_digits=5, decimal_places=2)

    objects = PriceManager()
    currency = 'US'

    class Meta:
        db_table = 'prices'

    def __unicode__(self):
        return u'%s - $%s USD' % (self.name, self.price)


class PriceCurrency(amo.models.ModelBase):
    currency = models.CharField(max_length=10,
                                choices=do_dictsort(amo.OTHER_CURRENCIES))
    price = models.DecimalField(max_digits=5, decimal_places=2)
    tier = models.ForeignKey(Price)

    class Meta:
        db_table = 'price_currency'
        verbose_name = 'Price currencies'

    def __unicode__(self):
        return u'%s, %s: %s' % (self.tier.name, self.currency, self.price)


class AddonPurchase(amo.models.ModelBase):
    addon = models.ForeignKey('addons.Addon')
    user = models.ForeignKey(UserProfile)
    receipt = models.TextField(default='')

    class Meta:
        db_table = 'addon_purchase'

    def __unicode__(self):
        return u'%s: %s' % (self.addon, self.user)

    def create_receipt(self):
        receipt = dict(typ='purchase-receipt',
                       product=self.addon.origin,
                       user={'type': 'email',
                             'value': self.user.email},
                       iss=settings.SITE_URL,
                       nbf=time.time(),
                       iat=time.time(),
                       detail='',  # Not implemented yet
                       #  Slugs can be edited, so lets us the pk.
                       verify=reverse('api.market.verify',
                                      args=[self.addon.pk]))
        self.receipt = jwt.encode(receipt, get_key())


def get_key():
    """Return a key for using with encode."""
    return jwt.rsa_load(settings.WEBAPPS_RECEIPT_KEY)


@receiver(models.signals.post_save, sender=AddonPurchase,
          dispatch_uid='create_receipt')
def create_receipt(sender, instance, **kw):
    """
    When the AddonPurchase gets created, see if we need to create a receipt.
    """
    if (kw.get('raw') or instance.addon.type != amo.ADDON_WEBAPP
        or instance.receipt):
        return

    log.debug('Creating receipt for: addon %s, user %s'
              % (instance.addon.pk, instance.user.pk))
    instance.create_receipt()
    instance.save()


@receiver(models.signals.post_save, sender=Contribution,
          dispatch_uid='create_addon_purchase')
def create_addon_purchase(sender, instance, **kw):
    """
    When the contribution table is updated with the data from PayPal,
    update the addon purchase table. Will figure out if we need to add to or
    delete from the AddonPurchase table.
    """
    if (kw.get('raw') or
        instance.type not in [amo.CONTRIB_PURCHASE, amo.CONTRIB_REFUND,
                              amo.CONTRIB_CHARGEBACK]):
        # Whitelist the types we care about. Forget about the rest.
        return

    log.debug('Processing addon purchase type: %s, addon %s, user %s'
              % (amo.CONTRIB_TYPES[instance.type], instance.addon.pk,
                 instance.user.pk))

    if instance.type == amo.CONTRIB_PURCHASE:
        log.debug('Creating addon purchase: addon %s, user %s'
                  % (instance.addon.pk, instance.user.pk))
        AddonPurchase.objects.create(addon=instance.addon, user=instance.user)

    elif instance.type in [amo.CONTRIB_REFUND, amo.CONTRIB_CHARGEBACK]:
        purchases = AddonPurchase.objects.filter(addon=instance.addon,
                                                 user=instance.user)
        for p in purchases:
            log.debug('Deleting addon purchase: %s, addon %s, user %s'
                      % (p.pk, instance.addon.pk, instance.user.pk))
            p.delete()


class AddonPremium(amo.models.ModelBase):
    """Additions to the Addon model that only apply to Premium add-ons."""
    addon = models.OneToOneField('addons.Addon')
    price = models.ForeignKey(Price, blank=True, null=True)
    paypal_permissions_token = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'addons_premium'

    def __unicode__(self):
        return u'Premium %s: %s' % (self.addon, self.price)
