import json
from StringIO import StringIO
from mock import patch
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils
from twitter import _process_tweet, search, _search_query, _prepare_lang


class TestFirefoxCup(test_utils.TestCase):

    def twitter_results(self):
        return StringIO(json.dumps({'results': [{'text': 'text'}]}))

    def test_prepare_lang(self):
        """Always use short lang code (e.g. en-US -> en)"""
        eq_(_prepare_lang('en-US'), 'en')

        """Bad lang codes should fall back to 'all'"""
        eq_(_prepare_lang('bad-lang-code'), 'all')

    def test_process_tweet(self):
        """URLs and tags are linkified"""

        a = map(_process_tweet,
            ['http://www.mozilla.com', '#hash', '@person'])

        for v in a:
            # use PyQuery to check for <a> tag
            assert pq(v).is_('a')

    def test_search_query_encoded(self):
        """Search query string is URL encoded"""

        a = _search_query(['foo', '#bar'], 'en')
        eq_(a, 'lang=en&ors=foo+%23bar')

    @patch('firefoxcup.twitter.urllib2.urlopen')
    def test_search_data_decoded(self, urlopen):
        """Search results are JSON decoded,
        and only the tweet content is returned"""
        urlopen.return_value = self.twitter_results()

        a = search([])
        eq_(a, ['text'])
