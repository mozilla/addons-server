import json
from StringIO import StringIO
import urllib2
from mock import patch
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils
from firefoxcup import twitter


class TestFirefoxCup(test_utils.TestCase):
    fixtures = ['addons/persona']

    def twitter_results(self):
        return StringIO(json.dumps({'results': [{'text': 'text'}]}))

    def test_prepare_lang(self):
        """Always use short lang code (e.g. en-US -> en)"""
        eq_(twitter._prepare_lang('es-ES'), 'es')

        """Bad lang codes should fall back to 'all'"""
        eq_(twitter._prepare_lang('bad-lang-code'), 'all')

    def test_process_tweet(self):
        """URLs and tags are linkified"""

        a = map(twitter._process_tweet,
            ['http://www.mozilla.com', '#hash', '@person'])

        for v in a:
            # use PyQuery to check for <a> tag
            assert pq(v).is_('a')

    def test_search_query_encoded(self):
        """Search query string is URL encoded"""

        a = twitter._search_query(['foo', '#bar'], 'en')
        eq_(a, 'ors=foo+%23bar')

    @patch('firefoxcup.twitter.urllib2.urlopen')
    def test_search_data_decoded(self, urlopen):
        """Search results are JSON decoded,
        and only the tweet content is returned"""
        urlopen.return_value = self.twitter_results()
        twitter.cache_tweets(lang='es-ES')

        a = twitter.search(lang='es-ES')
        eq_(a, ['text'])

    @patch('firefoxcup.twitter.urllib2.urlopen')
    def test_twitter_search_returns_list_on_error(self, urlopen):
        """If the call to the Twitter Search API fails,
        twitter.search() should not return None.  It should
        always return a list"""

        urlopen.side_effect = urllib2.URLError('Boom')
        eq_(twitter.search(lang='all'), [])
