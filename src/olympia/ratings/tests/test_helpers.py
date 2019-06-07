from django.template import engines

from pyquery import PyQuery as pq

from olympia.addons.models import Addon
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory
from olympia.amo.urlresolvers import reverse


class HelpersTest(TestCase):

    def render(self, s, context=None):
        if context is None:
            context = {}
        return engines['jinja2'].from_string(s).render(context)

    def test_stars(self):
        content = self.render('{{ num|stars }}', {'num': None})
        assert content == 'Not yet rated'

        doc = pq(self.render('{{ num|stars }}', {'num': 1}))
        msg = 'Rated 1 out of 5 stars'
        assert doc.attr('class') == 'stars stars-1'
        assert doc.attr('title') == msg
        assert doc.text() == msg

    def test_stars_details_page(self):
        doc = pq(self.render('{{ num|stars(large=True) }}', {'num': 2}))
        assert doc('.stars').attr('class') == 'stars large stars-2'

    def test_stars_max(self):
        doc = pq(self.render('{{ num|stars }}', {'num': 5.3}))
        assert doc.attr('class') == 'stars stars-5'

    def test_reviews_link(self):
        addon = addon_factory(
            average_rating=4, total_ratings=37, id=1, slug='xx')
        content = self.render(
            '{{ reviews_link(myaddon) }}', {'myaddon': addon})
        assert pq(content)('strong').text() == '37 reviews'

        # without collection uuid
        assert pq(content)('a').attr('href') == (
            'http://testserver/en-US/firefox/addon/xx/reviews/')

        # with collection uuid
        myuuid = 'f19a8822-1ee3-4145-9440-0a3640201fe6'
        content = self.render('{{ reviews_link(myaddon, myuuid) }}',
                              {'myaddon': addon, 'myuuid': myuuid})
        assert pq(content)('a').attr('href') == (
            'http://testserver/en-US/firefox/addon/xx/reviews/'
            '?collection_uuid=%s' % myuuid)

        addon2 = Addon(
            average_rating=0, total_ratings=0, id=1, type=1, slug='xx')
        content = self.render(
            '{{ reviews_link(myaddon) }}', {'myaddon': addon2})
        assert pq(content)('strong').text() == 'Not yet rated'

        # with link
        link = reverse('addons.ratings.list', args=['xx'])
        content = self.render('{{ reviews_link(myaddon) }}',
                              {'myaddon': addon})
        assert pq(content)('a').attr('href') == absolutify(link)

    def test_impala_reviews_link(self):
        addon = addon_factory(
            average_rating=4, total_ratings=37, id=1, slug='xx')
        content = self.render(
            '{{ impala_reviews_link(myaddon) }}', {'myaddon': addon})
        assert pq(content)('a').text() == '(37)'

        # without collection uuid
        assert pq(content)('a').attr('href') == (
            'http://testserver/en-US/firefox/addon/xx/reviews/')

        # with collection uuid
        myuuid = 'f19a8822-1ee3-4145-9440-0a3640201fe6'
        content = self.render('{{ impala_reviews_link(myaddon, myuuid) }}',
                              {'myaddon': addon, 'myuuid': myuuid})
        assert pq(content)('a').attr('href') == (
            'http://testserver/en-US/firefox/addon/xx/reviews/'
            '?collection_uuid=%s' % myuuid)

        addon2 = Addon(
            average_rating=0, total_ratings=0, id=1, type=1, slug='xx')
        content = self.render(
            '{{ impala_reviews_link(myaddon) }}', {'myaddon': addon2})
        assert pq(content)('b').text() == 'Not yet rated'

        # with link
        link = reverse('addons.ratings.list', args=['xx'])
        content = self.render(
            '{{ impala_reviews_link(myaddon) }}',
            {'myaddon': addon})
        assert pq(content)('a').attr('href') == absolutify(link)
