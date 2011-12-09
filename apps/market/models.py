# -*- coding: utf-8 -*-
from django.db import models
from django.dispatch import receiver
from django.utils import translation

from translations.fields import TranslatedField

import amo
from amo.decorators import write
import amo.models
from stats.models import Contribution
from users.models import UserProfile

from babel import Locale, numbers
import commonware.log
from jinja2.filters import do_dictsort
import paypal

log = commonware.log.getLogger('z.market')


class PriceManager(amo.models.ManagerBase):

    def get_query_set(self):
        qs = super(PriceManager, self).get_query_set()
        return qs.transform(Price.transformer)

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

    @staticmethod
    def transformer(prices):
        # There are a constrained number of price currencies, let's just
        # get them all.
        Price._currencies = dict([(p.currency, p.tier_id), p]
                                 for p in PriceCurrency.objects.all())

    def _price(self):
        """Return the price and currency for the current locale."""
        if not hasattr(self, '_currencies'):
            Price.transformer([])

        lang = translation.get_language()
        locale = Locale(translation.to_locale(lang))
        currency = amo.LOCALE_CURRENCY.get(locale.language)
        if currency:
            price_currency = Price._currencies.get((currency, self.id), None)
            if price_currency:
                return price_currency.price, currency, locale

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
    type = models.PositiveIntegerField(default=amo.CONTRIB_PURCHASE,
                                       choices=do_dictsort(amo.CONTRIB_TYPES),
                                       db_index=True)

    class Meta:
        db_table = 'addon_purchase'
        unique_together = ('addon', 'user')

    def __unicode__(self):
        return u'%s: %s' % (self.addon, self.user)


@write
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
              % (unicode(amo.CONTRIB_TYPES[instance.type]),
                 instance.addon.pk, instance.user.pk))

    if instance.type == amo.CONTRIB_PURCHASE:
        log.debug('Creating addon purchase: addon %s, user %s'
                  % (instance.addon.pk, instance.user.pk))

        data = {'addon': instance.addon, 'user': instance.user}
        purchase, created = AddonPurchase.objects.safer_get_or_create(**data)
        purchase.update(type=amo.CONTRIB_PURCHASE)
        from webapps.models import Installed  # Circular import.
        Installed.objects.safer_get_or_create(user=instance.user,
                                              addon=instance.addon)

    elif instance.type in [amo.CONTRIB_REFUND, amo.CONTRIB_CHARGEBACK]:
        purchases = AddonPurchase.objects.filter(addon=instance.addon,
                                                 user=instance.user)
        for p in purchases:
            log.debug('Changing addon purchase: %s, addon %s, user %s'
                      % (p.pk, instance.addon.pk, instance.user.pk))
            p.update(type=instance.type)


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
        Have we got a valid permissions token by pinging PayPal. If you've got
        'should_ignore_paypal', then it will just happily return True.
        """
        if paypal.should_ignore_paypal():
            return True
        if not self.paypal_permissions_token:
            return False
        return paypal.check_refund_permission(self.paypal_permissions_token)


class PreApprovalUser(amo.models.ModelBase):

    user = models.OneToOneField('users.UserProfile')
    paypal_key = models.CharField(max_length=255, blank=True, null=True)
    paypal_expiry = models.DateField(blank=True, null=True)

    class Meta:
        db_table = 'users_preapproval'
