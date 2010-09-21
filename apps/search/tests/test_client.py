import socket

from django.utils import translation
from django.conf import settings

import test_utils
import mock
from nose.tools import eq_, assert_raises
from pyquery import PyQuery as pq

import amo
from amo.urlresolvers import reverse
from bandwagon.models import Collection
from search.client import (extract_from_query, get_category_id,
                           Client as SearchClient, CollectionsClient,
                           PersonasClient, SearchError, )
from search.tests import SphinxTestCase


def test_extract_from_query():
    """Test that the correct terms are extracted from query strings."""

    eq_(("yslow ", "3.4",),
        extract_from_query("yslow voo:3.4", "voo", "[0-9.]+"))


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


class CollectionsSearchTest(SphinxTestCase):
    fixtures = ('base/collection_57181', 'base/apps',)

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


class CollectionsPrivateSearchTest(SphinxTestCase):
    fixtures = ('base/collection_57181', 'base/apps',)

    def setUp(self):
        c = Collection.objects.get(pk=57181)
        c.listed = False
        c.save()
        super(CollectionsPrivateSearchTest, self).setUp()

    def test_query(self):
        r = cquery("")
        eq_(r, [], "Collection shouldn't show up.")


class SearchDownTest(test_utils.TestCase):

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


class BadSortOptionTest(test_utils.TestCase):
    def test_bad_sort_option(self):
        """Test that we raise an error on bad sort options."""
        assert_raises(SearchError, lambda: query('xxx', sort="upsidedown"))


class SearchTest(SphinxTestCase):

    fixtures = ('base/addon_3615', 'base/addon_5369', 'base/addon_592',
                'base/addon_5579', 'base/addon_40', 'search/560618-alpha-sort',
                'base/apps', 'base/category')

    def test_guid_filter(self):
        """Filter by guid."""
        eq_(query('guid:{4c197c8f-a50f-4b49-a2d2-ed922c95612f}')[0].id, 592)

    def test_guid_filter_uppercase(self):
        """Filter by guids in whatever case I like."""
        eq_(query('guid:{4C197C8F-A50F-4B49-A2D2-ED922C95612F}')[0].id, 592)

    def test_guid_filter_email(self):
        eq_(query('guid:yslow@yahoo-inc.com')[0].id, 5369)

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
        """This tests that sphinx will properly restrict by version."""
        eq_(query("Delicious version:3.6")[0].id, 3615)
        eq_(len(query("Delicious version:4.0")), 0)

    def test_sorts(self):
        """
        This tests the various sorting.

        Note: These change if you change the fixtures.
        """
        eq_(query("", limit=1, sort='newest')[0].id, 11399)
        eq_(query("", limit=1, sort='updated')[0].id, 592,
            'Sort by updated is incorrect.')
        eq_(query("", limit=1, sort='name')[0].id, 11399)
        eq_(query("", limit=1, sort='averagerating')[0].id, 11399,
            'Sort by average rating is incorrect.')
        eq_(query("", limit=1, sort='weeklydownloads')[0].id, 5579)

    def test_app_filter(self):
        """
        This tests filtering by application id.
        """

        eq_(query('', limit=1, app=amo.MOBILE.id)[0].id, 11399)
        # Poor sunbird, nobody likes them.
        eq_(len(query('deli', app=amo.SUNBIRD.id)), 0)

    def test_category_filter(self):
        """This tests filtering by category."""

        eq_(len(query("Firebug category:feeds", app=amo.FIREFOX.id)), 0)

    def test_type_filter(self):
        """
        This tests filtering by addon type.
        """
        eq_(query("type:search", limit=1)[0].id, 11399)

    def test_platform_filter(self):
        """
        This tests filtering by platform.
        """
        eq_(len(query("CoolIris", platform='sunos')), 0)
        eq_(len(query("CoolIris", platform='macos')), 1)

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

    def test_summary(self):
        eq_(query("bookmarking")[0].id, 3615)  # Should get us Delicious


class RankingTest(SphinxTestCase):
    """This test assures that we don't regress our rankings."""

    fixtures = ('base/users',
                'base/addon_1833_yoono',
                'base/addon_9825_fastestfox',
               )

    def test_twitter(self):
        """
        Search for twitter should yield Yoono before FastestFox since Yoono has
        "twitter" in it's name field.
        """
        r = query('twitter')
        eq_(r[0].id, 1833)
        eq_(r[1].id, 9825)
