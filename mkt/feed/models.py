from django.db import models

import amo.models
import mkt.carriers
import mkt.regions
from addons.models import Category
from mkt.collections.models import Collection


class FeedItem(amo.models.ModelBase):
    """
    Allows objects from multiple models to be hung off the feed.
    """
    category = models.ForeignKey(Category, null=True, blank=True)
    region = models.PositiveIntegerField(default=None, null=True, blank=True,
                                         choices=mkt.regions.REGIONS_CHOICES_ID,
                                         db_index=True)
    carrier = models.IntegerField(default=None, null=True, blank=True,
                                  choices=mkt.carriers.CARRIER_CHOICES,
                                  db_index=True)

    # Types of objects that may be hung on a feed item.
    collection = models.ForeignKey(Collection, null=True)

    class Meta:
        db_table = 'mkt_feed_item'
