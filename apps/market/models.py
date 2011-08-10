# -*- coding: utf-8 -*-
from django.db import models

from translations.fields import TranslatedField

import amo
import amo.models

import commonware.log


log = commonware.log.getLogger('z.market')


class PriceManager(amo.models.ManagerBase):

    def active(self):
        return self.filter(active=True)


class Price(amo.models.ModelBase):

    active = models.BooleanField(default=True)
    name = TranslatedField()
    price = models.DecimalField(max_digits=5, decimal_places=2)

    objects = PriceManager()

    class Meta:
        db_table = 'prices'

    def __unicode__(self):
        return u'%s: %s' % (self.name, self.price)
