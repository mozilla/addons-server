# -*- coding: utf-8 -*-
from django.db import models

from translations.fields import TranslatedField

from addons.models import Addon
import amo
import amo.models
from users.models import UserProfile

import commonware.log
from jinja2.filters import do_dictsort


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
        return u'%s: %s' % (self.name, self.price)


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
    addon = models.ForeignKey(Addon)
    user = models.ForeignKey(UserProfile)

    class Meta:
        db_table = 'addon_purchase'

    def __unicode__(self):
        return u'%s: %s' % (self.addon, self.user)
