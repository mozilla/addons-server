import urllib

from django.contrib.syndication.views import Feed
from django.shortcuts import get_object_or_404

from tower import ugettext as _

import amo
from amo.urlresolvers import reverse
from amo.helpers import absolutify, url, _page_name
from addons.models import Category
from .views import addon_listing


class CategoriesRss(Feed):

    category = None
    request = None
    TYPE = amo.ADDON_EXTENSION

    def get_object(self, request, category_name):
        """
        Get the Category for which we are about to output
        the RSS feed of its Addons
        """
        self.request = request
        q = Category.objects.filter(application=request.APP.id, type=self.TYPE)
        self.category = get_object_or_404(q, slug=category_name)
        return self.category

    def title(self, category):
        """Title for the feed as a whole"""
        return u'%s :: %s' % (category.name, _page_name(self.request.APP))

    def link(self, category):
        """Link for the feed as a whole"""
        return absolutify(url('home'))

    def description(self, category):
        """Description for the feed as a whole"""
        return _('Addons for this category')

    def items(self, category):
        """Return the Addons for this Category to be output as RSS <item>'s"""
        addons, _, _ = addon_listing(self.request, self.TYPE, 'updated')
        return addons.filter(categories__id=category.id)[:30]

    def item_title(self, addon):
        """Title for particular addon (<item><title>...</)"""
        return u'%s %s' % (addon.name, addon.current_version)

    def item_link(self, addon):
        """Link for a particular addon (<item><link>...</)"""
        return absolutify(reverse('addons.detail', args=[addon.id]))

    def item_description(self, addon):
        """Description for particular addon (<item><description>...</)"""
        return addon.description

    def item_guid(self, addon):
        """Guid for a particuar addon (<item><guid>)"""
        guid_url = absolutify(reverse('addons.versions', args=[addon.id]))
        return guid_url + urllib.quote(str(addon.current_version))

    def item_author_name(self, addon):
        """Author for a particuar review  (<item><dc:creator>)"""
        if addon.listed_authors:
            return addon.listed_authors[0].display_name
        else:
            return ''

    def item_pubdate(self, addon):
        """Pubdate for a particuar review  (<item><pubDate>)"""
        return addon.created
