"""
Tests for the search (sphinx) app.
"""
import os
import shutil
import time

from django.test import TransactionTestCase

from nose.tools import eq_

from .utils import start_sphinx, stop_sphinx, reindex, convert_version
from .client import Client as SearchClient


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

    eq_(c(v[0],v[1]), -1)
    eq_(c(v[1],v[2]), -1)
    eq_(c(v[2],v[3]), 0)
    eq_(c(v[3],v[4]), -1)
    eq_(c(v[4],v[5]), -1)
    eq_(c(v[5],v[6]), 1)


class SphinxTest(TransactionTestCase):

    fixtures = ["search/sphinx.json"]
    sphinx = True

    def setUp(self):
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


    def tearDown(self):
        stop_sphinx()

    def test_sphinx_indexer(self):
        """
        This tests that sphinx will properly index an addon.
        """

        # we have to specify to sphinx to look at test_ dbs
        c = SearchClient()
        results = c.query('Delicious')
        assert results[0]['attrs']['addon_id'] == 3615, \
            "Didn't get the addon ID I wanted."
