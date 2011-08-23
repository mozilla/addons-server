from django import http
from django.contrib.syndication.views import Feed

from tower import ugettext as _

from amo.helpers import absolutify, page_name
from amo.urlresolvers import reverse
from access import acl
from addons.models import Addon
from browse.feeds import AddonFeedMixin
from . import views


class CollectionFeedMixin(Feed):
    """Common pieces for collections in a feed."""

    def item_link(self, c):
        return absolutify(c.get_url_path())

    def item_title(self, c):
        return unicode(c.name or '')

    def item_description(self, c):
        return unicode(c.description or '')

    def item_author_name(self, c):
        return c.author_username

    def item_pubdate(self, c):
        sort = self.request.GET.get('sort')
        return c.created if sort == 'created' else c.modified


class CollectionFeed(CollectionFeedMixin, Feed):

    request = None

    def get_object(self, request):
        self.request = request

    def title(self, c):
        app = page_name(self.request.APP)
        # L10n: {0} is 'Add-ons for <app>'.
        return _(u'Collections :: %s') % app

    def link(self):
        return absolutify(reverse('collections.list'))

    def description(self):
        return _('Collections are groups of related add-ons that anyone can '
                 'create and share.')

    def items(self):
        return views.get_filter(self.request).qs[:20]


class CollectionDetailFeed(AddonFeedMixin, Feed):

    def get_object(self, request, username, slug):
        self.request = request
        c = views.get_collection(request, username, slug)
        if not (c.listed or acl.check_collection_ownership(request, c)):
            # 403 can't be raised as an exception.
            raise http.Http404()
        return c

    def title(self, c):
        app = page_name(self.request.APP)
        # L10n: {0} is a collection name, {1} is 'Add-ons for <app>'.
        return _(u'{0} :: Collections :: {1}').format(c.name, app)

    def link(self, c):
        return absolutify(c.feed_url())

    def description(self, c):
        return c.description

    def items(self, c):
        addons = Addon.objects.valid() & c.addons.all()
        return addons.order_by('-collectionaddon__created')[:20]
