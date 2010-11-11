from django.contrib.syndication.views import Feed
from django.shortcuts import get_object_or_404
from django.utils.feedgenerator import Rss201rev2Feed as RSS

from amo.helpers import absolutify, url, strip_html
from devhub.models import ActivityLog, RssKey


class ActivityFeedRSS(Feed):
    feed_type = RSS

    def get_object(self, request):
        rsskey = request.GET.get('privaterss')
        key = get_object_or_404(RssKey, key=rsskey)
        return key

    def items(self, key):
        if key.addon:
            addons = key.addon
        else:  # We are showing all the add-ons.
            addons = key.user.addons.all()

        return ActivityLog.objects.for_addons(addons)[:20]

    def item_title(self, item):
        return strip_html(item.to_string())

    def link(self):
        """Link for the feed as a whole"""
        return absolutify(url('devhub.feed_all'))

    def item_link(self):
        return self.link()
