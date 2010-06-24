"""Tests for the search (sphinx) app."""
import os
import shutil
import socket
import time
import urllib

from django.test import TestCase, client
from django.utils import translation

import jingo
import mock
from nose import SkipTest
from nose.tools import eq_, assert_raises
from mock import Mock
from pyquery import PyQuery as pq
import test_utils

import amo
import amo.test_utils
from amo.urlresolvers import reverse
from amo.tests.test_helpers import render
from manage import settings
from search import forms, views
from search.utils import start_sphinx, stop_sphinx, reindex, convert_version
from search.client import (Client as SearchClient, CollectionsClient,
                           PersonasClient, SearchError, get_category_id,
                           extract_from_query)
from addons.models import Addon, Category
from tags.models import Tag


def test_convert_version():

    def c(x, y):
        x = convert_version(x)
        y = convert_version(y)

        if (x > y):
            return 1
        elif (x < y):
            return - 1

        return 0

    v = ['1.9.0a1pre', '1.9.0a1', '1.9.1.b5', '1.9.1.b5', '1.9.1pre',
         '1.9.1', '1.9.0']

    eq_(c(v[0], v[1]), -1)
    eq_(c(v[1], v[2]), -1)
    eq_(c(v[2], v[3]), 0)
    eq_(c(v[3], v[4]), -1)
    eq_(c(v[4], v[5]), -1)
    eq_(c(v[5], v[6]), 1)


def test_extract_from_query():
    """Test that the correct terms are extracted from query strings."""

    eq_(("yslow ", "3.4",),
        extract_from_query("yslow voo:3.4", "voo", "[0-9.]+"))


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


class SphinxTestCase(amo.test_utils.ExtraSetup,
                     test_utils.TransactionTestCase):
    """
    This test case type can setUp and tearDown the sphinx daemon.  Use this
    when testing any feature that requires sphinx.
    """

    fixtures = ['base/fixtures']
    sphinx = True
    sphinx_is_running = False

    def setUp(self):
        super(SphinxTestCase, self).setUp()

        if not SphinxTestCase.sphinx_is_running:
            if (not settings.SPHINX_SEARCHD or
                not settings.SPHINX_INDEXER):  # pragma: no cover
                raise SkipTest()

            os.environ['DJANGO_ENVIRONMENT'] = 'test'

            if os.path.exists(settings.SPHINX_CATALOG_PATH):
                shutil.rmtree(settings.SPHINX_CATALOG_PATH)
            if os.path.exists(settings.SPHINX_DATA_PATH):
                shutil.rmtree(settings.SPHINX_DATA_PATH)

            os.makedirs('/tmp/data/sphinx')
            os.makedirs('/tmp/log/searchd')
            reindex()
            start_sphinx()
            time.sleep(1)
            SphinxTestCase.sphinx_is_running = True

    @classmethod
    def tearDownClass(cls):
        if SphinxTestCase.sphinx_is_running:
            stop_sphinx()
            SphinxTestCase.sphinx_is_running = False


class GetCategoryIdTest(test_utils.TestCase):
    fixtures = ["base/category"]

    def test_get_category_id(self):
        """Tests that we get the expected category ids"""
        eq_(get_category_id('feeds', amo.FIREFOX.id), 1)


query = lambda *args, **kwargs: SearchClient().query(*args, **kwargs)
cquery = lambda *args, **kwargs: CollectionsClient().query(*args, **kwargs)
pquery = lambda *args, **kwargs: PersonasClient().query(*args, **kwargs)


@mock.patch('search.client.sphinx.SphinxClient')
def test_sphinx_timeout(sphinx_mock):
    def sphinx_error(cls):  # pragma: no cover
        raise cls

    sphinx_mock._filters = []
    sphinx_mock._limit = 10
    sphinx_mock._offset = 0
    sphinx_mock.return_value = sphinx_mock
    sphinx_mock.RunQueries.side_effect = lambda *a: sphinx_error(
            socket.timeout)
    assert_raises(SearchError, query, 'xxx')

    sphinx_mock.RunQueries.side_effect = lambda *a: sphinx_error(Exception)
    assert_raises(SearchError, query, 'xxx')

    sphinx_mock.Query.side_effect = lambda *a: sphinx_error(socket.timeout)
    assert_raises(SearchError, pquery, 'xxx')

    sphinx_mock.Query.side_effect = lambda *a: sphinx_error(Exception)
    assert_raises(SearchError, pquery, 'xxx')

    sphinx_mock.Query.side_effect = lambda *a: sphinx_error(socket.timeout)
    assert_raises(SearchError, cquery, 'xxx')

    sphinx_mock.Query.side_effect = lambda *a: sphinx_error(Exception)
    assert_raises(SearchError, cquery, 'xxx')


class BadSortOptionTest(TestCase):
    def test_bad_sort_option(self):
        """Test that we raise an error on bad sort options."""
        assert_raises(SearchError, lambda: query('xxx', sort="upsidedown"))


class SearchDownTest(TestCase):

    def test_search_down(self):
        """
        Test that we raise a SearchError if search is not running.
        """
        self.assertRaises(SearchError, query, "")

    def test_frontend_search_down(self):
        self.client.get('/')
        resp = self.client.get(reverse('search.search'))
        doc = pq(resp.content)
        eq_(doc('.no-results').length, 1)

    def test_collections_search_down(self):
        self.client.get('/')
        resp = self.client.get(reverse('search.search') + '?cat=collections')
        doc = pq(resp.content)
        eq_(doc('.no-results').length, 1)

    def test_personas_search_down(self):
        self.client.get('/')
        resp = self.client.get(reverse('search.search') + '?cat=personas')
        doc = pq(resp.content)
        eq_(doc('.no-results').length, 1)


class CollectionsSearchTest(SphinxTestCase):

    def test_query(self):
        r = cquery("")
        assert r.total > 0

    def test_sort_good(self):
        r = cquery("", sort='weekly')
        weekly = [c.weekly_subscribers for c in r]
        eq_(weekly, sorted(weekly, reverse=True))

    def test_sort_bad(self):
        assert_raises(SearchError, cquery, '', sort='fffuuu')

    def test_zero_results(self):
        r = query("ffffffffffffffffffffuuuuuuuuuuuuuuuuuuuu")
        eq_(r, [])


class SearchTest(SphinxTestCase):
    fixtures = SphinxTestCase.fixtures + ['search/560618-alpha-sort']

    def test_alpha_sort(self):
        "This verifies that alpha sort is case insensitive."
        c = SearchClient()
        results = c.query('', sort='name')
        ordering = [unicode(a.name).lower() for a in results]
        eq_(ordering, sorted(ordering))

    def test_sphinx_indexer(self):
        """
        This tests that sphinx will properly index an addon.
        """

        # we have to specify to sphinx to look at test_ dbs
        c = SearchClient()
        results = c.query('Delicious')
        assert results[0].id == 3615, \
            "Didn't get the addon ID I wanted."

    def test_version_restriction(self):
        """
        This tests that sphinx will properly restrict by version.
        """
        eq_(query("Firebug version:3.6")[0].id, 1843)
        eq_(len(query("Firebug version:4.0")), 0)

    def test_sorts(self):
        """
        This tests the various sorting.

        Note: These change if you change the fixtures.
        """
        eq_(query("", limit=1, sort='newest')[0].id, 11399)
        eq_(query("", limit=1, sort='updated')[0].id, 6113,
            'Sort by updated is incorrect.')
        eq_(query("", limit=1, sort='name')[0].id, 55)
        eq_(query("", limit=1, sort='averagerating')[0].id, 8680,
            'Sort by average rating is incorrect.')
        eq_(query("", limit=1, sort='weeklydownloads')[0].id, 55)

    def test_app_filter(self):
        """
        This tests filtering by application id.
        """

        eq_(query("", limit=1, app=amo.MOBILE.id)[0].id, 4664)
        # Poor sunbird, nobody likes them.
        eq_(len(query("Firebug", app=amo.SUNBIRD.id)), 0)

    def test_category_filter(self):
        """This tests filtering by category."""

        eq_(len(query("Firebug category:alerts", app=amo.FIREFOX.id)), 0)

    def test_type_filter(self):
        """
        This tests filtering by addon type.
        """

        eq_(query("type:theme", limit=1)[0].id, 7172)

    def test_platform_filter(self):
        """
        This tests filtering by platform.
        """
        eq_(len(query("grapple", platform='sunos')), 0)
        eq_(len(query("grapple", platform='macos')), 1)

    def test_namesort_filter(self):
        """
        Setting the language to 'fr' and sorting by 'name' should give us no
        results... since our fixture is fr-incapable.
        """
        translation.activate('fr')
        eq_(len(query("grapple", sort='name')), 0)
        translation.activate(settings.LANGUAGE_CODE)

    def test_locale_filter(self):
        """
        Similar to test_xenophobia_filter.
        """
        eq_(len(query("grapple", locale='fr')), 0)

    def test_status_filter(self):
        """
        Tests that if we filter for public addons that MozEx does not show up.
        If we look for sandboxed addons as well MozEx will show up.
        """

        eq_(len(query("MozEx", status=[amo.STATUS_PUBLIC])), 0)
        eq_(query("MozEx",
                  status=[amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED])[0].id, 40)

    def test_bad_chars(self):
        """ Sphinx doesn't like queries that are entirely '$', '^' or '^ $' """
        bad_guys = ('^', '$', '$ ^', '^ s $', '$s^', '  $ s  ^', ' ^  s  $',
                    '^$', '^    $', '||facebook.com^$third-party')

        for guy in bad_guys:
            try:
                query(guy, meta=('versions',))
            except SearchError:  # pragma: no cover
                assert False, "Error querying for %s" % guy


def test_form_version_label():
    for app in amo.APP_USAGE:
        r = client.Client().get('/en-US/{0}/'.format(app.short))
        doc = pq(r.content)
        eq_(doc('#advanced-search label')[0].text,
                '%s Version' % unicode(app.pretty))


class PersonaSearchTest(SphinxTestCase):
    fixtures = ['addons/persona']

    def get_response(self, **kwargs):
        return self.client.get(reverse('search.search') +
                               '?' + urllib.urlencode(kwargs))

    def test_default_personas_query(self):
        r = self.get_response(cat='personas')
        doc = pq(r.content)
        eq_(doc('title').text(),
                'Personas Search Results :: Add-ons for Firefox')
        eq_(len(doc('.secondary .categories h3')), 1)
        eq_(doc('.primary h3').text(), '1 Persona')
        eq_(len(doc('.persona-preview')), 1)
        eq_(doc('.thumbnails h4').text(), 'My Persona')
        eq_(doc('.thumbnails em').text(), '55 active daily users')


class FrontendSearchTest(SphinxTestCase):

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

    def test_default_query(self):
        """
        Verify some expected things on a query for nothing.
        """
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
        eq_(el, 'Search for delicious :: Add-ons for Firefox')

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
        eq_('GrApple Yummy', doc('.item h3 a').text())


class ViewTest(test_utils.TestCase):
    """Tests some of the functions used in building the view."""

    fixtures = ['base/fixtures']

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


class TestSearchForm(test_utils.TestCase):
    fixtures = ['base/fixtures', 'addons/persona']

    def test_get_app_versions(self):
        actual = forms.get_app_versions(amo.FIREFOX)
        expected = [('any', 'Any'), ('3.7', '3.7'), ('3.6', '3.6'),
                    ('3.5', '3.5'), ('3.0', '3.0'), ]

        # So you added a new appversion and this broke?  Sorry about that.
        eq_(actual, expected)

    def test_personas_selected(self):
        r = self.client.get(reverse('browse.personas'), follow=True)
        doc = pq(r.content)
        eq_(doc('#cat option:selected').val(), 'personas')

        # detail page
        r = self.client.get(reverse('addons.detail', args=[15663]),
                            follow=True)
        doc = pq(r.content)
        eq_(doc('#cat option:selected').val(), 'personas')

    def test_no_personas(self):
        """Sunbird, Mobile and Seamonkey don't have personas.  So don't
        persuade people to search for them."""
        apps = ('sunbird', 'mobile', 'seamonkey',)

        for app in apps:
            r = self.client.get('/en-US/%s/' % app, follow=True)
            doc = pq(r.content)
            eq_(len(doc('.cat-all [value=personas]')), 0,
                '%s shows personas' % app)


def test_showing_helper():
    tpl = "{{ showing(query, tag, pager) }}"
    pager = Mock()
    pager.start_index = lambda: 1
    pager.end_index = lambda: 20
    pager.paginator.count = 1000
    c = {}
    c['query'] = ''
    c['tag'] = ''
    c['pager'] = pager
    eq_('Showing 1 - 20 of 1000 results', render(tpl, c))
    c['tag'] = 'foo'
    eq_('Showing 1 - 20 of 1000 results tagged with <strong>foo</strong>',
            render(tpl, c))
    c['query'] = 'balls'
    eq_('Showing 1 - 20 of 1000 results for <strong>balls</strong> '
        'tagged with <strong>foo</strong>', render(tpl, c))
    c['tag'] = ''
    eq_('Showing 1 - 20 of 1000 results for <strong>balls</strong>',
        render(tpl, c))


def test_pagination_result_count():
    jingo.load_helpers()
    pager = Mock()
    pager.start_index = lambda: 1
    pager.end_index = lambda: 20
    pager.paginator.count = 999
    c = dict(pager=pager)
    eq_(u'Results <strong>1</strong>-<strong>20</strong> of '
        '<strong>999</strong>',
        render("{{ pagination_result_count(pager) }}", c))
