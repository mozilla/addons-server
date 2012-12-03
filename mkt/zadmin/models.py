from django.db import models

from addons.models import Category

import amo

import mkt
from mkt.webapps.models import Webapp


class FeaturedApp(amo.models.ModelBase):
    app = models.ForeignKey(Webapp, null=False)
    category = models.ForeignKey(Category, null=True)
    is_sponsor = models.BooleanField(default=False)
    start_date = models.DateField(null=True)
    end_date = models.DateField(null=True)

    class Meta:
        db_table = 'zadmin_featuredapp'


class FeaturedAppRegion(amo.models.ModelBase):
    featured_app = models.ForeignKey(FeaturedApp, null=False,
                                     related_name='regions')
    region = models.PositiveIntegerField(default=mkt.regions.WORLDWIDE.id,
                                         db_index=True)


class FeaturedAppCarrier(amo.models.ModelBase):
    featured_app = models.ForeignKey(FeaturedApp, null=False,
                                     related_name='carriers')
    carrier = models.CharField(max_length=255, db_index=True, null=False)
