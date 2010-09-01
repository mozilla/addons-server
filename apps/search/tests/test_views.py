# -*- coding: utf8 -*-
import json
import urllib

from django.test import client

from mock import Mock, patch
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

import amo
from amo.urlresolvers import reverse
from search.tests import SphinxTestCase
from search import views
from search.client import SearchError
from addons.models import Addon, Category
from tags.models import AddonTag, Tag
from users.models import UserProfile


def test_parse_bad_type():
    """
    Given a type that doesn't exist, we should not throw a KeyError.

    Note: This does not require sphinx to be running.
    """
    c = client.Client()
    try:
        c.get("/en-US/firefox/api/1.2/search/firebug%20type:dict")
    except KeyError:  # pragma: no cover
        assert False, ("We should not throw a KeyError just because we had a "
                       "nonexistent addon type.")


class PersonaSearchTest(SphinxTestCase):
    fixtures = ['base/apps', 'addons/persona']

    def get_response(self, **kwargs):
        return self.client.get(reverse('search.search') +
                               '?' + urllib.urlencode(kwargs))

    def test_default_personas_query(self):
        r = self.get_response(cat='personas')
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('title').text(),
                'Personas Search Results :: Add-ons for Firefox')


class FrontendSearchTest(SphinxTestCase):
    fixtures = ('base/addon_3615', 'base/appversions',
                'base/addon_6704_grapple')

    def setUp(self):
        # Warms up the prefixer.
        self.client.get('/')
        super(FrontendSearchTest, self).setUp()

    def get_response(self, **kwargs):
        return self.client.get(reverse('search.search') +
                               '?' + urllib.urlencode(kwargs))

    def test_xss(self):
        """Inputs should be escaped so people don't XSS."""
        r = self.get_response(q='><strong>My Balls</strong>')
        doc = pq(r.content)
        eq_(len([1 for a in doc('strong') if a.text == 'My Balls']), 0)

    def test_tag_xss(self):
        """Test that the tag params are escaped as well."""

        r = self.get_response(tag="<script>alert('balls')</script>")
        self.assertNotContains(r, "<script>alert('balls')</script>")

    def test_default_query(self):
        """Verify some expected things on a query for nothing."""
        resp = self.get_response()
        doc = pq(resp.content)
        num_actual_results = len(Addon.objects.filter(
            versions__apps__application=amo.FIREFOX.id,
            versions__files__gt=0))
        # Verify that we have the expected number of results.
        eq_(doc('.item').length, num_actual_results)

        # We should count the number of expected results and match.
        eq_(doc('h3.results-count').text(), "Showing 1 - %d of %d results"
           % (num_actual_results, num_actual_results, ))

        # Verify that we have the Refine Results.
        eq_(doc('.secondary .highlight h3').length, 1)

    def test_default_collections_query(self):
        r = self.get_response(cat='collections')
        doc = pq(r.content)
        eq_(doc('title').text(),
            'Collection Search Results :: Add-ons for Firefox')

    def test_basic_query(self):
        "Test a simple query"
        resp = self.get_response(q='delicious')
        doc = pq(resp.content)
        el = doc('title')[0].text_content().strip()
        eq_(el, 'Add-on Search Results for delicious :: Add-ons for Firefox')

    def test_redirection(self):
        resp = self.get_response(appid=18)
        self.assertRedirects(resp, '/en-US/thunderbird/search/?appid=18')

    def test_last_updated(self):
        """
        Verify that we have no new things in the last day.
        """
        resp = self.get_response(lup='1 day ago')
        doc = pq(resp.content)
        eq_(doc('.item').length, 0)

    def test_category(self):
        """
        Verify that we have nothing in category 72.
        """
        resp = self.get_response(cat='1,72')
        doc = pq(resp.content)
        eq_(doc('.item').length, 0)

    def test_addontype(self):
        resp = self.get_response(atype=amo.ADDON_LPAPP)
        doc = pq(resp.content)
        eq_(doc('.item').length, 0)

    def test_version_selected(self):
        "The selected version should match the lver param."
        resp = self.get_response(lver='3.6')
        doc = pq(resp.content)
        el = doc('#refine-compatibility li.selected')[0].text_content().strip()
        eq_(el, '3.6')

    def test_empty_version_selected(self):
        """If a user filters by a version that has no results, that version
        should show up on the filter list anyway."""
        resp = self.get_response(lver='3.6', q='adjkhasdjkasjkdhash')
        doc = pq(resp.content)
        el = doc('#refine-compatibility li.selected').text().strip()
        eq_(el, '3.6')

    def test_sort_newest(self):
        "Test that we selected the right sort."
        resp = self.get_response(sort='newest')
        doc = pq(resp.content)
        el = doc('.listing-header li.selected')[0].text_content().strip()
        eq_(el, 'Newest')

    def test_sort_default(self):
        "Test that by default we're sorting by Keyword Search"
        resp = self.get_response()
        doc = pq(resp.content)
        els = doc('.listing-header li.selected')
        eq_(len(els), 1, "No selected sort :(")
        eq_(els[0].text_content().strip(), 'Keyword Match')

    def test_sort_bad(self):
        "Test that a bad sort value won't bring the system down."
        self.get_response(sort='yermom')

    def test_non_existent_tag(self):
        """
        If you are searching for a tag that doesn't exist we shouldn't return
        any results.
        """
        resp = self.get_response(tag='stockholmsyndrome')
        doc = pq(resp.content)
        eq_(doc('.item').length, 0)

    def test_themes_in_results(self):
        """Many themes have platform ids that aren't 1, we should make sure we
        are returning them."""
        resp = self.get_response(q='grapple')
        doc = pq(resp.content)
        eq_(u'GrApple Yummy Aronnax', doc('.item h3 a').text())

    def test_tag_refinement(self):
        """Don't show the tag list if there's no tags to be shown."""
        r = self.get_response(q='vuvuzela')
        doc = pq(r.content)
        eq_(len(doc('.addon-tags')), 0)

    def test_pagination_refinement(self):
        """Refinement panel shouldn't have the page parameter in urls."""
        r = self.get_response(page=2)
        doc = pq(r.content)
        for link in doc('#refine-results a'):
            assert 'page=2' not in link.attrib['href'], (
                    "page parameter found in %s link" % link.text)

    def test_version_refinement(self):
        """For an addon, if we search for it, we get the
        full range of versions for refinement purposes."""
        # Delicious is 3.6-3.7 compatible
        r = self.get_response(q='delicious')
        doc = pq(r.content)
        eq_([a.text for a in doc(r.content)('#refine-compatibility a')],
            ['All Versions', '3.6'])

    def test_bad_cat(self):
        r = self.get_response(cat='1)f,ff')
        eq_(r.status_code, 200)


class ViewTest(test_utils.TestCase):
    """Tests some of the functions used in building the view."""

    fixtures = ('base/category',)

    def setUp(self):
        self.fake_request = Mock()
        self.fake_request.get_full_path = lambda: 'http://fatgir.ls/'

    def test_get_categories(self):
        cats = Category.objects.all()
        cat = cats[0].id

        # Select a category.
        items = views._get_categories(self.fake_request, cats, category=cat)
        eq_(len(cats), len(items[1].children))
        assert any((i.selected for i in items[1].children))

        # Select an addon type.
        atype = cats[0].type
        items = views._get_categories(self.fake_request, cats,
                                      addon_type=atype)
        assert any((i.selected for i in items))

    def test_get_tags(self):
        t = Tag(tag_text='yermom')
        assert views._get_tags(self.fake_request, tags=[t], selected='yermom')


class AjaxTest(SphinxTestCase):
    fixtures = ('base/addon_3615',)

    def test_json(self):
        r = self.client.get(reverse('search.ajax') + '?q=del')
        data = json.loads(r.content)

        check = lambda x, y: eq_(data[0][val], expected)

        addon = Addon.objects.get(pk=3615)
        check_me = (
                ('id', addon.id),
                ('icon', addon.icon_url),
                ('label', unicode(addon.name)),
                ('value', unicode(addon.name).lower()))

        for val, expected in check_me:
            check(val, expected)

    @patch('search.client.Client.query')
    def test_errors(self, searchclient):
        searchclient.side_effect = SearchError()
        r = self.client.get(reverse('search.ajax') + '?q=del')
        eq_('[]', r.content)


class AjaxDisabledAddonsTest(SphinxTestCase):
    fixtures = ('base/addon_3615',)

    def setUp(self):
        a = Addon.objects.get(pk=3615)
        a.status = amo.STATUS_DISABLED
        a.save()
        super(AjaxDisabledAddonsTest, self).setUp()

    def test_json(self):
        r = self.client.get(reverse('search.ajax') + '?q=del')
        eq_('[]', r.content)


class TagTest(SphinxTestCase):
    fixtures = ('base/apps', 'addons/persona',)

    def setUp(self):
        u = UserProfile(username='foo')
        u.save()
        t = Tag(tag_text='donkeybuttrhino')
        t.save()
        a = Addon.objects.all()[0]
        at = AddonTag(tag=t, user=u, addon=a)
        at.save()
        super(TagTest, self).setUp()

    def test_persona_results(self):
        url = reverse('tags.detail', args=('donkeybuttrhino',))
        r = self.client.get(url, follow=True)
        eq_(len(r.context['pager'].object_list), 1)
