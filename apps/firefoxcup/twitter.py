from urllib import urlencode
from urllib2 import urlopen, URLError
import logging
import ttp
import json
from django.core.cache import cache
import config
from hashlib import md5
from bleach import Bleach

log = logging.getLogger('z.firefoxcup')
parser = ttp.Parser()
bleach = Bleach()

def _prepare_lang(lang):
    lang = lang.split('-')[0]
    if lang not in config.twitter_languages:
        lang = 'all'
    return lang

def _search_query(tags, lang):
    return urlencode({
        'ors': ' '.join(tags),
        'lang': lang})

def search(tags, lang='all', check_cache=True, open=urlopen):
    lang = _prepare_lang(lang)


    url = "http://search.twitter.com/search.json?" + _search_query(tags, lang)

    # build cache key
    hash = md5(url).hexdigest()
    cache_key = "%s:%s" % ("firefoxcup-twitter", hash)
    cache_time = 60

    if (check_cache):
        cached = cache.get(cache_key)
        if (cached):
            return cached

    try:
        json_data = open(url)
    except URLError, e:
        log.error("Couldn't open (%s): %s" % (url, e))
        return

    # decode JSON
    data = json.load(json_data)['results']
    # we only want the text, throw the other data away
    tweets = [tweet['text'] for tweet in data]
    tweets = map( _process_tweet, tweets)
        
    cache.set(cache_key, tweets, cache_time)
    return tweets

def _process_tweet(tweet):
    # linkify urls, tags (e.g. #hashtag, @someone)
    tweet = parser.parse(tweet).html
    tweet = bleach.clean(tweet, tags=['a'],
                         attributes={'a': ['href', 'rel']})
    return tweet
    
