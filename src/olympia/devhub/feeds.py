import uuid

from django import http
from django.contrib.syndication.views import Feed
from django.shortcuts import get_object_or_404
from django.utils.feedgenerator import Rss201rev2Feed
from django.utils.translation import gettext

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.templatetags.jinja_helpers import absolutify, url
from olympia.devhub.models import RssKey
from olympia.translations.templatetags.jinja_helpers import clean as clean_html


class ActivityFeedRSS(Feed):
    feed_type = Rss201rev2Feed

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
            addons = key.user.addons.all()

        return (
            ActivityLog.objects.for_addons(addons).exclude(
                action__in=amo.LOG_HIDE_DEVELOPER
            )
        )[:20]

    def item_title(self, item):
        return clean_html(item.to_string(), True)

    def title(self, key):
        """Title for the feed as a whole"""
        if key.addon:
            return gettext('Recent Changes for %s') % key.addon
        else:
            return gettext('Recent Changes for My Add-ons')

    def link(self):
        """Link for the feed as a whole"""
        return absolutify(url('devhub.feed_all'))

    def item_link(self):
        return self.link()

    def item_guid(self):
        pass
