import uuid

from django import http
from django.contrib.syndication.views import Feed
from django.shortcuts import get_object_or_404
from django.utils.feedgenerator import Rss201rev2Feed
from django.utils.translation import gettext

import nh3

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.templatetags.jinja_helpers import absolutify, url
from olympia.amo.utils import clean_nl
from olympia.devhub.models import RssKey


class ActivityFeedRSS(Feed):
    feed_type = Rss201rev2Feed

    def get_object(self, request):
        try:
            rsskey = request.GET.get('privaterss')
            rsskey = uuid.UUID(rsskey)
        except ValueError as exc:
            raise http.Http404 from exc

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

    def clean_html(self, string):
        return clean_nl(nh3.clean(str(string), tags=set())).strip()

    def item_title(self, item):
        return self.clean_html(item.to_string())

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
