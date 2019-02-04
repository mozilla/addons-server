from django.shortcuts import get_object_or_404
from django.utils.feedgenerator import DefaultFeed
from django.utils.translation import ugettext

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.feeds import BaseFeed
from olympia.amo.templatetags.jinja_helpers import absolutify, format_date, url
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import urlparams
from olympia.versions.views import PER_PAGE


class PagedFeed(DefaultFeed):

    page = None

    def add_page_relation(self, handler, rel, page):
        page = None if page == 1 else page
        url = urlparams(self.feed['feed_url'], page=page)
        handler.addQuickElement('atom:link', None, {'rel': rel, 'href': url})

    def add_root_elements(self, handler):
        # set feed_url to current page
        page = None if self.page.number == 1 else self.page.number
        self.feed['feed_url'] = urlparams(self.feed['feed_url'], page=page)
        DefaultFeed.add_root_elements(self, handler)

        # http://tools.ietf.org/html/rfc5005#section-3
        self.add_page_relation(handler, 'first', 1)
        if self.page.has_previous():
            self.add_page_relation(handler, 'previous',
                                   self.page.previous_page_number())
        if self.page.has_next():
            self.add_page_relation(handler, 'next',
                                   self.page.next_page_number())
        self.add_page_relation(handler, 'last', self.page.paginator.num_pages)


class VersionsRss(BaseFeed):

    feed_type = PagedFeed
    addon = None

    def get_object(self, request, addon_id):
        """Get the Addon for which we are about to output
           the RSS feed of it Versions"""
        qs = Addon.objects
        self.addon = get_object_or_404(qs.id_or_slug(addon_id) & qs.valid())

        status_list = amo.VALID_FILE_STATUSES
        items_qs = (self.addon.versions
                    .filter(files__status__in=status_list)
                    .distinct().order_by('-created'))
        self.feed_type.page = amo.utils.paginate(request, items_qs, PER_PAGE)
        return self.addon

    def title(self, addon):
        """Title for the feed"""
        return ugettext(u'%s Version History' % addon.name)

    def link(self, addon):
        """Link for the feed"""
        return absolutify(url('home'))

    def description(self, addon):
        """Description for the feed"""
        return ugettext('Version History with Changelogs')

    def items(self, obj):
        """Return the Versions for this Addon to be output as RSS <item>'s"""
        return self.feed_type.page

    def item_link(self, version):
        """Link for a particular version (<item><link>)"""
        return absolutify(version.get_url_path())

    def item_title(self, version):
        """Title for particular version (<item><title>)"""
        # L10n: This is the Title for this Version of the Addon
        return u'{name} {version} - {created}'.format(
            name=self.addon.name, version=version.version,
            created=format_date(version.created))

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
