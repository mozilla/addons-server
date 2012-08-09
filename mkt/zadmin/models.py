from django.db import models

from addons.models import Category

import mkt
from mkt.webapps.models import Webapp


class FeaturedApp(models.Model):
    app = models.ForeignKey(Webapp, null=False)
    category = models.ForeignKey(Category, null=True)
    is_sponsor = models.BooleanField(default=False)

    class Meta:
        db_table = 'zadmin_featuredapp'


class FeaturedAppRegionExclusion(models.Model):
    featured_app = models.ForeignKey(FeaturedApp, null=False)
    region = models.PositiveIntegerField(default=mkt.regions.WORLDWIDE.id,
                                         db_index=True)

    class Meta:
        db_table = 'zadmin_featuredapp_regionexclusion'
