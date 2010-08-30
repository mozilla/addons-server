from django.contrib.syndication.views import Feed
from django.shortcuts import get_object_or_404
from jingo.helpers import datetime

from tower import ugettext as _

import amo
from amo.urlresolvers import reverse
from amo.helpers import absolutify, url

from addons.models import Addon


class VersionsRss(Feed):

    addon = None

    def get_object(self, request, addon_id):
        """Get the Addon for which we are about to output
           the RSS feed of it Versions"""
        self.addon = get_object_or_404(Addon.objects.valid(), pk=addon_id)
        return self.addon

    def title(self, addon):
        """Title for the feed"""
        return _('%s Version History') % addon.name

    def link(self, addon):
        """Link for the feed"""
        return absolutify(url('home'))

    def description(self, addon):
        """Description for the feed"""
        return _('Version History with Changelogs')

    def items(self, obj):
        """Return the Versions for this Addon to be output as RSS <item>'s"""
        qs = (obj.versions.filter(files__status__in=amo.VALID_STATUSES)
              .distinct().order_by('-created'))
        return qs.all()[:30]

    def item_link(self, version):
        """Link for a particular version (<item><link>)"""
        return absolutify(reverse('addons.versions', args=[version.addon_id,
                                                           version.version]))

    def item_title(self, version):
        """Title for particular version (<item><title>)"""
        # L10n: This is the Title for this Version of the Addon
        return u'{name} {version} - {created}'.format(
            name=self.addon.name, version=version.version,
                 created=datetime(version.created))

    def item_description(self, version):
        """Description for particular version (<item><description>)"""
        return version.releasenotes

    def item_guid(self, version):
        """Guid for a particuar version  (<item><guid>)"""
        url = absolutify(reverse('addons.versions', args=[version.addon_id]))
        return "%s#version-%s" % (url, version.version)

    def item_author_name(self, version):
        """Author for a particuar version  (<item><dc:creator>)"""
        # @todo should be able to output a <dc:creator for each author
        if version.addon.listed_authors:
            return version.addon.listed_authors[0].name
        else:
            return ''

    def item_pubdate(self, version):
        """Pubdate for a particuar version  (<item><pubDate>)"""
        return version.created
