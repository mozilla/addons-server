# -*- coding: utf-8 -*-
from django.core.cache import cache
from django.db import connection, models
from django.dispatch import receiver
from django.utils import translation

from translations.fields import TranslatedField

import amo
import amo.models
from amo.decorators import write
from amo.utils import get_locale_from_lang, memoize_key
from stats.models import Contribution
from users.models import UserProfile

import commonware.log
import json_field
import paypal
from babel import numbers
from jinja2.filters import do_dictsort

log = commonware.log.getLogger('z.market')


class PriceManager(amo.models.ManagerBase):

    def get_query_set(self):
        qs = super(PriceManager, self).get_query_set()
        return qs.transform(Price.transformer)

    def active(self):
        return self.filter(active=True).order_by('price')


class Price(amo.models.ModelBase):
    active = models.BooleanField(default=True)
    name = TranslatedField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

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

    def get_price_data(self, currency=None):
        """Returns a tuple of Decimal(price), currency, locale.

        The price is the actual price in the current locale.
        That is, if the instance is tier 1 ($0.99) and the current locale
        maps to Euros then you get 5,01 EUR or whatever the exchange is.

        If currency is None, the default currency from the current locale will
        be returned. If you do pass in an explicit currency, you will still
        get the currently active locale which may or may not match.
        """
        if not hasattr(self, '_currencies'):
            Price.transformer([])

        lang = translation.get_language()
        locale = get_locale_from_lang(lang)
        if not currency:
            currency = amo.LOCALE_CURRENCY.get(locale.language)
        if currency:
            price_currency = Price._currencies.get((currency, self.id), None)
            if price_currency:
                return price_currency.price, currency, locale

        return self.price, currency or self.currency, locale

    def get_price(self, currency=None):
        """Return the price as a decimal for the current locale."""
        return self.get_price_data(currency=currency)[0]

    def get_price_locale(self, currency=None):
        """Return the price as a nicely localised string for the locale."""
        price, currency, locale = self.get_price_data(currency=currency)
        return numbers.format_currency(price, currency, locale=locale)

    def currencies(self):
        """A listing of all the currency objects for this tier."""
        if not hasattr(self, '_currencies'):
            Price.transformer([])

        currencies = [('USD', self)]
        currencies.extend([(c.currency, c)
                           for c in self._currencies.values()
                           if c.tier_id == self.pk])
        return currencies


class PriceCurrency(amo.models.ModelBase):
    currency = models.CharField(max_length=10,
                                choices=do_dictsort(amo.OTHER_CURRENCIES))
    price = models.DecimalField(max_digits=10, decimal_places=2)
    tier = models.ForeignKey(Price)

    class Meta:
        db_table = 'price_currency'
        verbose_name = 'Price currencies'
        unique_together = ('tier', 'currency')

    def get_price_locale(self):
        """Return the price as a nicely localised string for the locale."""
        lang = translation.get_language()
        locale = get_locale_from_lang(lang)
        return numbers.format_currency(self.price, self.currency,
                                       locale=locale)

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
        from mkt.webapps.models import Installed  # Circular import.
        Installed.objects.safer_get_or_create(user=instance.user,
                                              addon=instance.addon)

    elif instance.type in [amo.CONTRIB_REFUND, amo.CONTRIB_CHARGEBACK]:
        purchases = AddonPurchase.objects.filter(addon=instance.addon,
                                                 user=instance.user)
        for p in purchases:
            log.debug('Changing addon purchase: %s, addon %s, user %s'
                      % (p.pk, instance.addon.pk, instance.user.pk))
            p.update(type=instance.type)

    cache.delete(memoize_key('users:purchase-ids', instance.user.pk))


class AddonPremium(amo.models.ModelBase):
    """Additions to the Addon model that only apply to Premium add-ons."""
    addon = models.OneToOneField('addons.Addon')
    price = models.ForeignKey(Price, blank=True, null=True)
    paypal_permissions_token = models.CharField(max_length=255, blank=True)
    currencies = json_field.JSONField(default={})

    class Meta:
        db_table = 'addons_premium'

    def __unicode__(self):
        return u'Premium %s: %s' % (self.addon, self.price)

    def has_price(self):
        return self.price is not None

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
        return paypal.check_permission(self.paypal_permissions_token,
                                       ['REFUND'])

    def supported_currencies(self):
        """
        Return a list of the supported currencies for this app.
        You get a list of tuples of currency name and the price currency
        object.

        USD will always be present since that is the default.
        """
        currencies = self.currencies or {}
        return [c for c in self.price.currencies()
                if c[0] in currencies or c[0] == 'USD']


class PreApprovalUser(amo.models.ModelBase):

    user = models.OneToOneField('users.UserProfile')
    paypal_key = models.CharField(max_length=255, blank=True, null=True)
    paypal_expiry = models.DateField(blank=True, null=True)
    currency = models.CharField(max_length=3, blank=True, null=True)

    class Meta:
        db_table = 'users_preapproval'


class RefundManager(amo.models.ManagerBase):

    def by_addon(self, addon):
        return self.filter(contribution__addon=addon)

    def pending(self, addon=None):
        return self.by_addon(addon).filter(status=amo.REFUND_PENDING)

    def approved(self, addon):
        return self.by_addon(addon).filter(status=amo.REFUND_APPROVED)

    def instant(self, addon):
        return self.by_addon(addon).filter(status=amo.REFUND_APPROVED_INSTANT)

    def declined(self, addon):
        return self.by_addon(addon).filter(status=amo.REFUND_DECLINED)

    def failed(self, addon):
        return self.by_addon(addon).filter(status=amo.REFUND_FAILED)


class Refund(amo.models.ModelBase):
    # This refers to the original object with `type=amo.CONTRIB_PURCHASE`.
    contribution = models.OneToOneField('stats.Contribution')

    # Pending => 0
    # Approved => 1
    # Instantly Approved => 2
    # Declined => 3
    # Failed => 4
    status = models.PositiveIntegerField(default=amo.REFUND_PENDING,
        choices=do_dictsort(amo.REFUND_STATUSES), db_index=True)

    refund_reason = models.TextField(default='', blank=True)
    rejection_reason = models.TextField(default='', blank=True)

    # Date `created` should always be date `requested` for pending refunds,
    # but let's just stay on the safe side. We might change our minds.
    requested = models.DateTimeField(null=True, db_index=True)
    approved = models.DateTimeField(null=True, db_index=True)
    declined = models.DateTimeField(null=True, db_index=True)

    objects = RefundManager()

    class Meta:
        db_table = 'refunds'

    def __unicode__(self):
        return u'%s (%s)' % (self.contribution, self.get_status_display())

    @staticmethod
    def post_save(sender, instance, **kwargs):
        from amo.tasks import find_refund_escalations
        find_refund_escalations(instance.contribution.addon_id)

    @classmethod
    def recent_refund_ratio(cls, addon_id, since):
        """
        Returns the ratio of purchases to refunds since the given datetime.
        """
        cursor = connection.cursor()
        purchases = AddonPurchase.objects.filter(
            addon=addon_id, type=amo.CONTRIB_PURCHASE).count()

        if purchases == 0:
            return 0.0

        params = [addon_id, since]
        # Hardcoded statuses for simplicity, but they are:
        # amo.REFUND_PENDING, amo.REFUND_APPROVED, amo.REFUND_APPROVED_INSTANT
        sql = '''
            SELECT COUNT(DISTINCT user_id) AS num
            FROM refunds
            LEFT JOIN stats_contributions AS sc
                ON refunds.contribution_id = sc.id
            WHERE sc.addon_id = %s
            AND refunds.status IN (0,1,2)
            AND refunds.created > %s
        '''
        cursor.execute(sql, params)
        row = cursor.fetchone()
        if row:
            return row[0] / float(purchases)
        return 0.0


models.signals.post_save.connect(Refund.post_save, sender=Refund)


class AddonPaymentData(amo.models.ModelBase):
    # Store information about the app. This can be entered manually
    # or got from PayPal. At the moment, I'm just capturing absolutely
    # everything from PayPal and that's what these fields are.
    # Easier to do this and clean out later.
    # See: http://bit.ly/xy5BTs and http://bit.ly/yRYbRx
    #
    # I've no idea what the biggest lengths of these are, so making
    # up some aribtrary lengths.
    addon = models.OneToOneField('addons.Addon', related_name='payment_data')
    # Basic.
    first_name = models.CharField(max_length=255, blank=True)
    last_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    full_name = models.CharField(max_length=255, blank=True)
    business_name = models.CharField(max_length=255, blank=True)
    country = models.CharField(max_length=64)
    payerID = models.CharField(max_length=255, blank=True)
    # Advanced.
    address_one = models.CharField(max_length=255)
    address_two = models.CharField(max_length=255, blank=True)
    post_code = models.CharField(max_length=128, blank=True)
    city = models.CharField(max_length=128, blank=True)
    state = models.CharField(max_length=64, blank=True)
    phone = models.CharField(max_length=32, blank=True)

    class Meta:
        db_table = 'addon_payment_data'

    @classmethod
    def address_fields(cls):
        return [field.name for field in cls._meta.fields
                if isinstance(field, (models.CharField, models.EmailField))]

    def __unicode__(self):
        return u'%s: %s' % (self.pk, self.addon)


class PaypalCheckStatus(amo.models.ModelBase):
    addon = models.ForeignKey('addons.Addon')
    failure_data = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'paypal_checkstatus'
