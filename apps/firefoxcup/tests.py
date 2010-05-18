import json
from twitter import _process_tweet, search, _search_query, _prepare_lang
from pyquery import PyQuery as pq
from nose.tools import eq_
from StringIO import StringIO
from django.test.client import Client
from mock import Mock

def test_view():
    """View returns 200"""
    c = Client()
    res = c.get('/en-US/firefox/firefoxcup/')
    eq_(res.status_code, 200)
    
def test_prepare_lang():
    """Always use short lang code (e.g. en-US -> en)"""
    eq_(_prepare_lang('en-US'), 'en')

    """Bad lang codes should fall back to 'all'""" 
    eq_(_prepare_lang('bad-lang-code'), 'all')

def test_process_tweet():
    """URLs and tags are linkified"""
    a = map(_process_tweet, ['http://www.mozilla.com', '#hash', '@person'])
    for v in a:
        # use PyQuery to check for <a> tag
        assert pq(v).is_('a')

def test_search_query_encoded():
    """Search query string is URL encoded"""
    a = _search_query(['foo', '#bar'], 'en')
    eq_(a, 'lang=en&ors=foo+%23bar')

def test_search_data_decoded():
    """Search results are JSON decoded, and only the tweet content is returned"""
    mock = Mock()
    mock.open = lambda url: StringIO(json.dumps( {'results': [{'text': 'text'}]} ))

    a = search([], open=mock.open)
    eq_(a, ['text'])

