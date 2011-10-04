# -*- coding: utf-8 -*-
import time

from django.conf import settings
from django.db import models
from django.dispatch import receiver
from django.utils import translation

from translations.fields import TranslatedField

import amo
import amo.models
from amo.urlresolvers import reverse
from stats.models import Contribution
from users.models import UserProfile

from babel import Locale, numbers
import commonware.log
from jinja2.filters import do_dictsort
import jwt
import paypal

log = commonware.log.getLogger('z.market')


class PriceManager(amo.models.ManagerBase):

    def active(self):
        return self.filter(active=True)


class Price(amo.models.ModelBase):
    active = models.BooleanField(default=True)
    name = TranslatedField()
    price = models.DecimalField(max_digits=5, decimal_places=2)

    objects = PriceManager()
    currency = 'USD'

    class Meta:
        db_table = 'prices'

    def __unicode__(self):
        return u'%s - $%s' % (self.name, self.price)

    def _price(self):
        """Return the price and currency for the current locale."""
        lang = translation.get_language()
        locale = Locale(translation.to_locale(lang))
        currency = amo.LOCALE_CURRENCY.get(locale.language)
        if currency:
            price_currency = self.pricecurrency_set.filter(currency=currency)
            if price_currency:
                return price_currency[0].price, currency, locale

        return self.price, self.currency, locale

    def get_price(self):
        """Return the price as a decimal for the current locale."""
        return self._price()[0]

    def get_price_locale(self):
        """Return the price as a nicely localised string for the locale."""
        price, currency, locale = self._price()
        return numbers.format_currency(price, currency, locale=locale)


class PriceCurrency(amo.models.ModelBase):
    currency = models.CharField(max_length=10,
                                choices=do_dictsort(amo.OTHER_CURRENCIES))
    price = models.DecimalField(max_digits=5, decimal_places=2)
    tier = models.ForeignKey(Price)

    class Meta:
        db_table = 'price_currency'
        verbose_name = 'Price currencies'

    def __unicode__(self):
        return u'%s, %s: %s' % (self.tier, self.currency, self.price)


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
                       detail=reverse('users.purchases.receipt',
                                      args=[self.addon.pk]),
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
        AddonPurchase.objects.get_or_create(addon=instance.addon,
                                            user=instance.user)

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

    def get_price(self):
        return self.price.get_price()

    def get_price_locale(self):
        return self.price.get_price_locale()

    def is_complete(self):
        return bool(self.addon and self.price and
                    self.addon.paypal_id and self.addon.support_email)

    def has_permissions_token(self):
        """
        Have we got a permissions token. If you've got 'should_ignore_paypal'
        enabled, then it will just happily return True.
        """
        return bool(paypal.should_ignore_paypal() or
                    self.paypal_permissions_token)

    def has_valid_permissions_token(self):
        """
        Have we got a valid permissions token by ping paypal. If you've got
        'should_ignore_paypal', then it will just happily return True.
        """
        if paypal.should_ignore_paypal():
            return True
        if not self.paypal_permissions_token:
            return False
        return paypal.check_refund_permission(self.paypal_permissions_token)
