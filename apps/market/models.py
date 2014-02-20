# -*- coding: utf-8 -*-
from operator import itemgetter

from django.core.cache import cache
from django.db import connection, models
from django.dispatch import receiver
from django.forms.models import model_to_dict
from django.utils import translation

import commonware.log
from babel import numbers
from cache_nuggets.lib import memoize_key
from jinja2.filters import do_dictsort
from tower import ugettext_lazy as _

import amo
import amo.models
from amo.decorators import write
from amo.utils import get_locale_from_lang
from constants.payments import (CARRIER_CHOICES, PAYMENT_METHOD_ALL,
                                PAYMENT_METHOD_CHOICES, PROVIDER_BANGO,
                                PROVIDER_CHOICES)
from lib.constants import ALL_CURRENCIES
from stats.models import Contribution
from users.models import UserProfile


log = commonware.log.getLogger('z.market')


def price_locale(price, currency):
    lang = translation.get_language()
    locale = get_locale_from_lang(lang)
    pricestr = numbers.format_currency(price, currency, locale=locale)
    if currency == 'EUR':
        # See bug 865358. EU style guide
        # (http://publications.europa.eu/code/en/en-370303.htm#position)
        # disagrees with Unicode CLDR on placement of Euro symbol.
        bare = pricestr.strip(u'\xa0\u20ac')
        if lang.startswith(('en', 'ga', 'lv', 'mt')):
            return u'\u20ac' + bare
        else:
            return bare + u'\xa0\u20ac'
    return pricestr


def price_key(data):
    return ('carrier={carrier}|tier={tier}|region={region}|provider={provider}'
            .format(**data))


class PriceManager(amo.models.ManagerBase):

    def get_query_set(self):
        qs = super(PriceManager, self).get_query_set()
        return qs.transform(Price.transformer)

    def active(self):
        return self.filter(active=True).order_by('price')


class Price(amo.models.ModelBase):
    active = models.BooleanField(default=True)
    name = models.CharField(max_length=4)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    # The payment methods availble for this tier.
    method = models.IntegerField(choices=PAYMENT_METHOD_CHOICES,
                                 default=PAYMENT_METHOD_ALL)

    objects = PriceManager()

    class Meta:
        db_table = 'prices'

    def tier_name(self):
        # L10n: %s is the name of the price tier, eg: 10.
        return _('Tier %s' % self.name)

    def tier_locale(self, currency='USD'):
        # A way to display the price of the tier.
        return price_locale(self.price, currency)

    def __unicode__(self):
        return u'$%s' % self.price

    @staticmethod
    def transformer(prices):
        # There are a constrained number of price currencies, let's just
        # get them all.
        Price._currencies = dict((price_key(model_to_dict(p)), p)
                                 for p in PriceCurrency.objects.all())

    def get_price_currency(self, carrier=None, region=None, provider=None):
        """
        Returns the PriceCurrency object or none.

        :param optional carrier: an int for the carrier.
        :param optional region: an int for the region. Defaults to restofworld.
        :param optional provider: an int for the provider. Defaults to bango.
        """
        region = region or RESTOFWORLD.id
        provider = provider or PROVIDER_BANGO
        if not hasattr(self, '_currencies'):
            Price.transformer([])

        lookup = price_key({
            'tier': self.id, 'carrier': carrier,
            'provider': provider, 'region': region
        })

        try:
            price_currency = Price._currencies[lookup]
        except KeyError:
            return None

        return price_currency

    def get_price_data(self, carrier=None, region=None, provider=None):
        """
        Returns a tuple of Decimal(price), currency, locale.

        :param optional carrier: an int for the carrier.
        :param optional region: an int for the region. Defaults to restofworld.
        :param optional provider: an int for the provider. Defaults to bango.
        """
        price_currency = self.get_price_currency(carrier=carrier,
                                                 region=region,
                                                 provider=provider)
        if price_currency:
            return price_currency.price, price_currency.currency
        return None, None

    def get_price(self, carrier=None, region=None, provider=None):
        """Return the price as a decimal for the current locale."""
        return self.get_price_data(carrier=carrier, region=region,
                                   provider=provider)[0]

    def get_price_locale(self, carrier=None, region=None, provider=None):
        """Return the price as a nicely localised string for the locale."""
        price, currency = self.get_price_data(carrier=carrier, region=region,
                                              provider=provider)
        if price is not None and currency is not None:
            return price_locale(price, currency)

    def prices(self, provider=None):
        """A list of dicts of all the currencies and prices for this tier."""
        provider = provider or PROVIDER_BANGO
        return [model_to_dict(o) for o in
                self.pricecurrency_set.filter(provider=provider)]

    def region_ids_by_slug(self):
        """A tuple of price region ids sorted by slug."""
        price_regions_ids = [(p['region'], RID.get(p['region']).slug)
                             for p in self.prices() if p['paid'] is True]
        if price_regions_ids:
            return zip(*sorted(price_regions_ids, key=itemgetter(1)))[0]
        return tuple()


class PriceCurrency(amo.models.ModelBase):
    # The carrier for this currency.
    carrier = models.IntegerField(choices=CARRIER_CHOICES, blank=True,
                                  null=True)
    currency = models.CharField(max_length=10,
                                choices=do_dictsort(ALL_CURRENCIES))
    price = models.DecimalField(max_digits=10, decimal_places=2)

    # The payments provider for this tier.
    provider = models.IntegerField(choices=PROVIDER_CHOICES, blank=True,
                                   null=True)

    # The payment methods allowed for this tier.
    method = models.IntegerField(choices=PAYMENT_METHOD_CHOICES,
                                 default=PAYMENT_METHOD_ALL)

    # These are the regions as defined in mkt/constants/regions.
    region = models.IntegerField(default=1)  # Default to restofworld.
    tier = models.ForeignKey(Price)

    # If this should show up in the developer hub.
    dev = models.BooleanField(default=True)

    # If this can currently accept payments from users.
    paid = models.BooleanField(default=True)

    class Meta:
        db_table = 'price_currency'
        verbose_name = 'Price currencies'
        unique_together = ('tier', 'currency', 'carrier', 'region',
                           'provider')

    def __unicode__(self):
        return u'%s, %s: %s' % (self.tier, self.currency, self.price)


@receiver(models.signals.post_save, sender=PriceCurrency,
          dispatch_uid='save_price_currency')
@receiver(models.signals.post_delete, sender=PriceCurrency,
          dispatch_uid='delete_price_currency')
def update_price_currency(sender, instance, **kw):
    """
    Ensure that when PriceCurrencies are updated, all the apps that use them
    are re-indexed into ES so that the region information will be correct.
    """
    if kw.get('raw'):
        return

    try:
        ids = list(instance.tier.addonpremium_set
                           .values_list('addon_id', flat=True))
    except Price.DoesNotExist:
        return

    if ids:
        log.info('Indexing {0} add-ons due to PriceCurrency changes'
                 .format(len(ids)))

        # Circular import sad face.
        from addons.tasks import index_addons
        index_addons.delay(ids)


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

    if instance.type in [amo.CONTRIB_REFUND, amo.CONTRIB_CHARGEBACK]:
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

    class Meta:
        db_table = 'addons_premium'

    def __unicode__(self):
        return u'Premium %s: %s' % (self.addon, self.price)

    def is_complete(self):
        return bool(self.addon and self.price and
                    self.addon.paypal_id and self.addon.support_email)


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
    user = models.ForeignKey('users.UserProfile')

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
            SELECT COUNT(DISTINCT sc.user_id) AS num
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
