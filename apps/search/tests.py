"""
Tests for the search (sphinx) app.
"""
import os
import shutil
import time

from django.test import TestCase, TransactionTestCase
from django.core.management import call_command
from django.utils import translation

from nose.tools import eq_

import amo
import settings
from .utils import start_sphinx, stop_sphinx, reindex, convert_version
from .client import Client as SearchClient, SearchError, get_category_id, extract_from_query


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
        eq_(query("", limit=1, sort='name')[0].id, 3615)
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
