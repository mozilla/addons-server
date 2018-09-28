import urllib

from django.shortcuts import get_object_or_404
from django.utils.translation import ugettext

from olympia.addons.models import Addon
from olympia.amo.feeds import BaseFeed
from olympia.amo.templatetags import jinja_helpers
from olympia.ratings.models import Rating


class RatingsRss(BaseFeed):

    addon = None

    def get_object(self, request, addon_id=None):
        """Get the Addon for which we are about to output
           the RSS feed of its Rating"""
        self.addon = get_object_or_404(Addon.objects.id_or_slug(addon_id))
        return self.addon

    def title(self, addon):
        """Title for the feed"""
        return ugettext(u'Reviews for %s') % addon.name

    def link(self, addon):
        """Link for the feed"""
        return jinja_helpers.absolutify(jinja_helpers.url('home'))

    def description(self, addon):
        """Description for the feed"""
        return ugettext('Review History for this Addon')

    def items(self, addon):
        """Return the Ratings for this Addon to be output as RSS <item>'s"""
        qs = (Rating.without_replies.all().filter(
            addon=addon).order_by('-created'))
        return qs.all()[:30]

    def item_link(self, rating):
        """Link for a particular rating (<item><link>)"""
        return jinja_helpers.absolutify(jinja_helpers.url(
            'addons.ratings.detail', self.addon.slug, rating.id))

    def item_title(self, rating):
        """Title for particular rating (<item><title>)"""
        title = ''
        if getattr(rating, 'rating', None):
            # L10n: This describes the number of stars given out of 5
            title = ugettext('Rated %d out of 5 stars') % rating.rating
        return title

    def item_description(self, rating):
        """Description for particular rating (<item><description>)"""
        return rating.body

    def item_guid(self, rating):
        """Guid for a particuar rating  (<item><guid>)"""
        guid_url = jinja_helpers.absolutify(
            jinja_helpers.url('addons.ratings.list', self.addon.slug))
        return guid_url + urllib.quote(str(rating.id))

    def item_author_name(self, rating):
        """Author for a particular rating  (<item><dc:creator>)"""
        return rating.user.name

    def item_pubdate(self, rating):
        """Pubdate for a particular rating  (<item><pubDate>)"""
        return rating.created
