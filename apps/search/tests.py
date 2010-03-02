"""
Tests for the search (sphinx) app.
"""
import os
import shutil
import time

from django.test import TestCase, TransactionTestCase, client
from django.core.management import call_command
from django.utils import translation

from nose import SkipTest
from nose.tools import eq_
import test_utils

import amo.helpers
from manage import settings
from search import forms
from search.utils import start_sphinx, stop_sphinx, reindex, convert_version
from search.client import (Client as SearchClient, SearchError,
                           get_category_id, extract_from_query)


def test_convert_version():

    def c(x, y):
        x = convert_version(x)
        y = convert_version(y)

        if (x > y):
            return 1
        elif (x < y):
            return - 1

        return 0

    v = ['1.9.0a1pre', '1.9.0a1', '1.9.1.b5', '1.9.1.b5', '1.9.1pre', \
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
    except KeyError:
        assert False, ("We should not throw a KeyError just because we had a "
                       "nonexistant addon type.")


class SphinxTestCase(TransactionTestCase):
    """
    This test case type can setUp and tearDown the sphinx daemon.  Use this
    when testing any feature that requires sphinx.
    """

    fixtures = ["base/addons.json"]
    sphinx = True
    sphinx_is_running = False

    def setUp(self):
        if not SphinxTestCase.sphinx_is_running:
            if not settings.SPHINX_SEARCHD or not settings.SPHINX_INDEXER:
                raise SkipTest()

            os.environ['DJANGO_ENVIRONMENT'] = 'test'

            if os.path.exists('/tmp/data/sphinx'):
                shutil.rmtree('/tmp/data/sphinx')
            if os.path.exists('/tmp/log/searchd'):
                shutil.rmtree('/tmp/log/searchd')

            os.makedirs('/tmp/data/sphinx')
            os.makedirs('/tmp/log/searchd')
            reindex()
            start_sphinx()
            time.sleep(1)
            SphinxTestCase.sphinx_is_running = True

    @classmethod
    def tearDownClass(cls):
        call_command('flush', verbosity=0, interactive=False)
        if SphinxTestCase.sphinx_is_running:
            stop_sphinx()
            SphinxTestCase.sphinx_is_running = False


class GetCategoryIdTest(TestCase):
    fixtures = ["base/category"]

    def test_get_category_id(self):
        """Tests that we get the expected category ids"""
        eq_(get_category_id('feeds', amo.FIREFOX.id), 1)


query = lambda *args, **kwargs: SearchClient().query(*args, **kwargs)


class SearchDownTest(TestCase):

    def test_search_down(self):
        """
        Test that we raise a SearchError if search is not running.
        """
        self.assertRaises(SearchError, query, "")


class SearchTest(SphinxTestCase):

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
        """
        eq_(query("", limit=1, sort='newest')[0].id, 10869)
        eq_(query("", limit=1, sort='updated')[0].id, 4664)
        eq_(query("", limit=1, sort='name')[0].id, 5299)
        eq_(query("", limit=1, sort='averagerating')[0].id, 7172)
        eq_(query("", limit=1, sort='weeklydownloads')[0].id, 55)

    def test_app_filter(self):
        """
        This tests filtering by application id.
        """

        eq_(query("", limit=1, app=amo.MOBILE.id)[0].id, 4664)
        # Poor sunbird, nobody likes them.
        eq_(len(query("", limit=1, app=amo.SUNBIRD.id)), 0)

    def test_category_filter(self):
        """
        This tests filtering by category.
        """

        eq_(len(query("Firebug category:alerts", app=amo.FIREFOX.id)), 0)
        eq_(len(query("category:alerts", app=amo.MOBILE.id)), 1)

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

    def test_xenophobia_filter(self):
        """
        Setting the language to 'fr' and turning xenophobia should give us no
        results... since our fixture is fr incapable.
        """
        translation.activate('fr')
        eq_(len(query("grapple", xenophobia=True)), 0)
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
                  status=[amo.STATUS_PUBLIC, amo.STATUS_SANDBOX])[0].id, 40)


class TestSearchForm(test_utils.TestCase):
    fixtures = ['base/addons']

    def test_get_app_versions(self):
        actual = forms.get_app_versions()
        expected = {
            amo.FIREFOX.id: ['2.0', '3.0', '3.5', '3.6', '3.7'],
            amo.THUNDERBIRD.id: [],
            amo.SUNBIRD.id: [],
            amo.SEAMONKEY.id: [],
            amo.MOBILE.id: ['1.0'],
        }
        for app in expected:
            expected[app] = [(k, k) for k in expected[app]]
            expected[app].append(('Any', 'any'))
        # So you added a new appversion and this broke?  Sorry about that.
        eq_(actual, expected)
