from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
from amo.utils import urlparams
from addons.models import AddonCategory, Category
from mkt.webapps.models import Webapp


class TestCategories(amo.tests.ESTestCase):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        self.cat = Category.objects.create(name='Lifestyle', slug='lifestyle',
                                           type=amo.ADDON_WEBAPP)
        self.url = reverse('browse.apps', args=[self.cat.slug])
        self.webapp = Webapp.objects.get(id=337141)
        AddonCategory.objects.create(addon=self.webapp, category=self.cat)
        self.webapp.save()
        self.refresh()

    def test_good_cat(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'search/results.html')

    def test_bad_cat(self):
        r = self.client.get(reverse('browse.apps', args=['xxx']))
        eq_(r.status_code, 404)

    def test_non_indexed_cat(self):
        new_cat = Category.objects.create(name='Slap Tickling', slug='booping',
                                          type=amo.ADDON_WEBAPP)
        r = self.client.get(reverse('browse.apps', args=[new_cat.slug]))

        # If the category has no indexed apps, we redirect to main search page.
        self.assertRedirects(r, reverse('search.search'))

    def test_sidebar(self):
        r = self.client.get(self.url)
        a = pq(r.content)('#category-facets .selected a')
        eq_(a.attr('href'),
            urlparams(reverse('search.search'), cat=self.cat.id))
        eq_(a.text(), unicode(self.cat.name))

    def test_sorter(self):
        r = self.client.get(self.url)
        li = pq(r.content)('#sorter li:eq(0)')
        eq_(li.attr('class'), 'selected')
        eq_(li.find('a').attr('href'),
            urlparams(reverse('search.search'), cat=self.cat.id,
                      sort='downloads'))

    def test_search_category(self):
        # Ensure category got preserved in search term.
        r = self.client.get(self.url)
        eq_(pq(r.content)('#search input[name=cat]').val(), str(self.cat.id))
