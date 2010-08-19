from django.contrib.syndication.views import Feed
from django.shortcuts import get_object_or_404

from tower import ugettext as _

from amo.urlresolvers import reverse
from amo.helpers import absolutify, url

from addons.models import Addon, Review

import urllib


class ReviewsRss(Feed):

    addon = None

    def get_object(self, request, addon_id):
        """Get the Addon for which we are about to output
           the RSS feed of it Review"""
        self.addon = get_object_or_404(Addon.objects.valid(), pk=addon_id)
        return self.addon

    def title(self, addon):
        """Title for the feed"""
        return _(u'Reviews for %s') % addon.name

    def link(self, addon):
        """Link for the feed"""
        return absolutify(url('home'))

    def description(self, addon):
        """Description for the feed"""
        return _('Review History for this Addon')

    def items(self, addon):
        """Return the Reviews for this Addon to be output as RSS <item>'s"""
        qs = (Review.objects.valid().filter(addon=addon).order_by('-created'))
        return qs.all()[:30]

    def item_link(self, review):
        """Link for a particular review (<item><link>)"""
        return absolutify(reverse('reviews.detail', args=[self.addon.id,
                                                          review.id]))

    def item_title(self, review):
        """Title for particular review (<item><title>)"""
        tag_line = rating = ''
        if getattr(review, 'rating', None):
            # L10n: This describes the number of stars given out of 5
            rating = _('Rated %d out of 5 stars') % review.rating
        if getattr(review, 'title', None):
            tag_line = review.title
        divider = ' : ' if rating and tag_line else ''
        return u'%s%s%s' % (rating, divider, tag_line)

    def item_description(self, review):
        """Description for particular review (<item><description>)"""
        return review.body

    def item_guid(self, review):
        """Guid for a particuar review  (<item><guid>)"""
        guid_url = absolutify(reverse('reviews.list', args=[self.addon.id]))
        return guid_url + urllib.quote(str(review.id))

    def item_author_name(self, review):
        """Author for a particuar review  (<item><dc:creator>)"""
        user = review.user
        if user.username:
            return user.username.strip()
        else:
            return '%s %s' % (user.firstname.strip(), user.lastname.strip())

    def item_pubdate(self, review):
        """Pubdate for a particuar review  (<item><pubDate>)"""
        return review.created
