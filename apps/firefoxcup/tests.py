from datetime import date, timedelta
import json
from StringIO import StringIO
from mock import patch
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils
from twitter import _process_tweet, search, _search_query, _prepare_lang
from .models import Stats
from .cron import firefoxcup_stats


class TestFirefoxCup(test_utils.TestCase):
    fixtures = ['addons/persona']

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

    def test_cron_popularity_history(self):
        teams = [{
            'name': 'test',
            'persona_id': 813,
        }]

        """If no records exist, one is created"""
        eq_(Stats.objects.count(), 0)
        # @patch('firefoxcup.cron.teams_config') didn't work :( why?
        firefoxcup_stats(teams=teams)
        eq_(Stats.objects.count(), 1)

        """If a recent record exists (< 1 day), don't create a new one"""
        firefoxcup_stats(teams=teams)
        eq_(Stats.objects.count(), 1)

        """If latest record is older than 1 day, create a new record"""
        latest = Stats.objects.latest()
        latest.created = date.today() - timedelta(days=1)
        latest.save()
        firefoxcup_stats(teams=teams)
        eq_(Stats.objects.count(), 2)

    def test_stats_avg(self):
        """Stats manager should pull average popularity grouped by persona"""
        Stats.objects.create(persona_id=5, popularity=6)
        Stats.objects.create(persona_id=5, popularity=2)

        Stats.objects.create(persona_id=6, popularity=5)
        Stats.objects.create(persona_id=6, popularity=15)

        avgs = {}
        for row in Stats.objects.avg_fans():
            avgs[row['persona_id']] = row['average']

        eq_(avgs[5], 4)
        eq_(avgs[6], 10)
