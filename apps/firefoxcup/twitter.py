from hashlib import md5
import json
from urllib import urlencode
import urllib2

from django.core.cache import cache

from bleach import Bleach
import commonware.log
import jinja2
import ttp

from . import twitter_languages

log = commonware.log.getLogger('z.firefoxcup')
parser = ttp.Parser()
bleach = Bleach()


def _prepare_lang(lang):
    lang = lang.split('-')[0]
    if lang not in twitter_languages:
        lang = 'all'
    return lang


def _search_query(tags, lang):
    return urlencode({
        'ors': ' '.join(tags),
        'lang': lang})


def search(tags, lang='all', check_cache=True):
    lang = _prepare_lang(lang)

    url = "http://search.twitter.com/search.json?" + _search_query(tags, lang)

    # build cache key
    hash = md5(url).hexdigest()
    cache_key = "%s:%s" % ("firefoxcup-twitter", hash)
    cache_time = 60

    if check_cache:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        json_data = urllib2.urlopen(url)
    except urllib2.URLError, e:
        log.error("Couldn't open (%s): %s" % (url, e))
        return

    # decode JSON
    data = json.load(json_data)['results']
    # we only want the text, throw the other data away
    tweets = [tweet['text'] for tweet in data]
    tweets = map(_process_tweet, tweets)

    cache.set(cache_key, tweets, cache_time)
    return tweets


def _process_tweet(tweet):
    # linkify urls, tags (e.g. #hashtag, @someone)
    tweet = parser.parse(tweet).html
    return jinja2.Markup(tweet)
