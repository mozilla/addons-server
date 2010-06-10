from hashlib import md5
import json
import urllib2

from django.conf import settings
from django.core.cache import cache
from django.utils.http import urlencode

import commonware.log
import jinja2
import ttp

from translations.models import LinkifiedTranslation

import firefoxcup as fxcup
from . import twitter_languages

log = commonware.log.getLogger('z.firefoxcup')
parser = ttp.Parser()


def _prepare_lang(lang):
    lang = lang.split('-')[0]
    if lang not in fxcup.tags:
        lang = 'all'
    return lang


def _search_query(tags, lang):
    return urlencode({'ors': ' '.join(tags)})


def search(lang, limit=15):
    key = _cache_key(_prepare_lang(lang))
    tweets = cache.get(key, [])
    if len(tweets) < limit and key != 'all':
        tweets.extend(cache.get(_cache_key('all'), []))
    return tweets[:limit]


def _cache_key(lang):
    return '%s:fxcup-twitter:%s' % (settings.CACHE_PREFIX, lang)


def cache_tweets(lang):
    lang = _prepare_lang(lang)
    tags = fxcup.tags[lang]
    url = "http://search.twitter.com/search.json?" + _search_query(tags, lang)

    # build cache key
    hash = md5(url).hexdigest()
    cache_key = _cache_key(lang)

    try:
        json_data = urllib2.urlopen(url)
    except urllib2.URLError, e:
        log.error("Couldn't open (%s): %s" % (url, e))
        return []

    try:
        # decode JSON
        data = json.load(json_data)['results']
    except (ValueError, KeyError):
        return []

    # we only want the text, throw the other data away
    tweets = [tweet['text'] for tweet in data]
    tweets = map(_process_tweet, tweets)

    log.debug('Caching %s tweets for %s' % (len(tweets), lang))
    cache.set(cache_key, tweets, 0)


def _process_tweet(tweet):
    # linkify urls, tags (e.g. #hashtag, @someone)
    tweet = parser.parse(tweet).html
    s = LinkifiedTranslation(localized_string=tweet)
    s.clean()
    return jinja2.Markup(s.localized_string_clean)
