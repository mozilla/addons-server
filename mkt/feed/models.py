from django.db import models

import amo.models
import mkt.carriers
import mkt.regions
from addons.models import Category, Preview
from mkt.collections.models import Collection
from mkt.webapps.models import Webapp
from reviews.models import Review
from translations.fields import PurifiedField, save_signal


class FeedApp(amo.models.ModelBase):
    """
    Thin wrapper around the Webapp class that allows single apps to be featured
    on the feed.
    """
    app = models.ForeignKey(Webapp)
    description = PurifiedField()
    rating = models.ForeignKey(Review, null=True, blank=True)
    preview = models.ForeignKey(Preview, null=True, blank=True)

    class Meta:
        db_table = 'mkt_feed_app'


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

    # Types of objects that may be contained by a feed item.
    app = models.ForeignKey(FeedApp, null=True)
    collection = models.ForeignKey(Collection, null=True)

    class Meta:
        db_table = 'mkt_feed_item'


# Save translations when saving a Feedapp instance.
models.signals.pre_save.connect(save_signal, sender=FeedApp,
                                dispatch_uid='feedapp_translations')
