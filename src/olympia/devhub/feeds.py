import uuid

from django import http
from django.contrib.syndication.views import Feed
from django.shortcuts import get_object_or_404
from django.utils.feedgenerator import Rss201rev2Feed as RSS
from django.utils.translation import ugettext as _

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo.helpers import absolutify, url, strip_html
from olympia.devhub.models import RssKey


class ActivityFeedRSS(Feed):
    feed_type = RSS

    def get_object(self, request):
        try:
            rsskey = request.GET.get('privaterss')
            rsskey = uuid.UUID(rsskey)
        except ValueError:
            raise http.Http404

        key = get_object_or_404(RssKey, key=rsskey.hex)
        return key

    def items(self, key):
        if key.addon:
            addons = key.addon
        else:  # We are showing all the add-ons
            addons = Addon.objects.filter(authors=key.user)

        return (ActivityLog.objects.for_addons(addons)
                           .exclude(action__in=amo.LOG_HIDE_DEVELOPER))[:20]

    def item_title(self, item):
        return strip_html(item.to_string())

    def title(self, key):
        """Title for the feed as a whole"""
        if key.addon:
            return _(u'Recent Changes for %s') % key.addon
        else:
            return _(u'Recent Changes for My Add-ons')

    def link(self):
        """Link for the feed as a whole"""
        return absolutify(url('devhub.feed_all'))

    def item_link(self):
        return self.link()

    def item_guid(self):
        pass
