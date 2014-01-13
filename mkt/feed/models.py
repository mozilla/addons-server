from django.core.exceptions import ValidationError
from django.db import models

import amo.models
import mkt.carriers
import mkt.regions
from addons.models import Category, Preview
from mkt.collections.models import Collection
from mkt.ratings.validators import validate_rating
from mkt.webapps.models import Webapp
from translations.fields import PurifiedField, save_signal


class FeedApp(amo.models.ModelBase):
    """
    Thin wrapper around the Webapp class that allows single apps to be featured
    on the feed.
    """
    app = models.ForeignKey(Webapp)
    description = PurifiedField()

    # Optionally linked to a Preview (screenshot or video).
    preview = models.ForeignKey(Preview, null=True, blank=True)

    # Optionally linked to a pull quote.
    pullquote_rating = models.PositiveSmallIntegerField(null=True, blank=True,
        validators=[validate_rating])
    pullquote_text = PurifiedField(null=True)
    pullquote_attribution = PurifiedField(null=True)

    class Meta:
        db_table = 'mkt_feed_app'

    def clean(self):
        """
        Require `pullquote_text` if `pullquote_rating` or
        `pullquote_attribution` are set.
        """
        if not self.pullquote_text and (self.pullquote_rating or
                                        self.pullquote_attribution):
            raise ValidationError('Pullquote text required if rating or '
                                  'attribution is defined.')
        super(FeedApp, self).clean()


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
