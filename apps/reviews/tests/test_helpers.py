from nose.tools import eq_

import jingo
from pyquery import PyQuery as pq

import amo.tests
from addons.models import Addon
from amo.urlresolvers import reverse
from reviews.models import ReviewFlag
from reviews.forms import ReviewForm


class HelpersTest(amo.tests.TestCase):

    def render(self, s, context={}):
        t = jingo.env.from_string(s)
        return t.render(context)

    def test_stars(self):
        s = self.render('{{ num|stars }}', {'num': None})
        assert s == 'Not yet rated'

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
        a = Addon(average_rating=4, total_reviews=37, id=1, type=1, slug='xx')
        s = self.render('{{ reviews_link(myaddon) }}', {'myaddon': a})
        assert pq(s)('strong').text() == '37 reviews'
        assert pq(s)('a').attr('href') == '/en-US/firefox/addon/xx/#reviews'

        # with collection uuid
        myuuid = 'f19a8822-1ee3-4145-9440-0a3640201fe6'
        s = self.render('{{ reviews_link(myaddon, myuuid) }}',
                        {'myaddon': a, 'myuuid': myuuid})
        assert pq(s)('a').attr('href') == '/en-US/firefox/addon/xx/?collection_uuid=%s#reviews' % myuuid

        z = Addon(average_rating=0, total_reviews=0, id=1, type=1, slug='xx')
        s = self.render('{{ reviews_link(myaddon) }}', {'myaddon': z})
        assert pq(s)('strong').text() == 'Not yet rated'

        # with link
        u = reverse('addons.reviews.list', args=['xx'])
        s = self.render('{{ reviews_link(myaddon, link_to_list=True) }}',
                        {'myaddon': a})
        assert pq(s)('a').attr('href') == u

    def test_impala_reviews_link(self):
        a = Addon(average_rating=4, total_reviews=37, id=1, type=1, slug='xx')
        s = self.render('{{ impala_reviews_link(myaddon) }}', {'myaddon': a})
        assert pq(s)('a').text() == '(37)'
        assert pq(s)('a').attr('href') == '/en-US/firefox/addon/xx/#reviews'

        # with collection uuid
        myuuid = 'f19a8822-1ee3-4145-9440-0a3640201fe6'
        s = self.render('{{ impala_reviews_link(myaddon, myuuid) }}',
                        {'myaddon': a, 'myuuid': myuuid})
        assert pq(s)('a').attr('href') == '/en-US/firefox/addon/xx/?collection_uuid=%s#reviews' % myuuid

        z = Addon(average_rating=0, total_reviews=0, id=1, type=1, slug='xx')
        s = self.render('{{ impala_reviews_link(myaddon) }}', {'myaddon': z})
        assert pq(s)('b').text() == 'Not yet rated'

        # with link
        u = reverse('addons.reviews.list', args=['xx'])
        s = self.render(
            '{{ impala_reviews_link(myaddon, link_to_list=True) }}',
            {'myaddon': a})
        assert pq(s)('a').attr('href') == u

    def test_mobile_reviews_link(self):
        def s(a):
            return pq(self.render('{{ mobile_reviews_link(myaddon) }}',
                                  {'myaddon': a}))

        a = Addon(total_reviews=0, id=1, type=1, slug='xx')
        doc = s(a)
        assert doc('a').attr('href') == reverse('addons.reviews.add', args=['xx'])

        u = reverse('addons.reviews.list', args=['xx'])

        a = Addon(average_rating=4, total_reviews=37, id=1, type=1, slug='xx')
        doc = s(a)
        assert doc('a').attr('href') == u
        assert doc('a').text() == 'Rated 4 out of 5 stars See All 37 Reviews'

        a = Addon(average_rating=4, total_reviews=1, id=1, type=1, slug='xx')
        doc = s(a)
        doc.remove('div')
        assert doc('a').attr('href') == u
        assert doc('a').text() == 'See All Reviews'

    def test_report_review_popup(self):
        doc = pq(self.render('{{ report_review_popup() }}'))
        assert doc('.popup.review-reason').length == 1
        for flag, text in ReviewFlag.FLAGS:
            assert doc('li a[href$=%s]' % flag).text() == text
        assert doc('form input[name=note]').length == 1

    def test_edit_review_form(self):
        doc = pq(self.render('{{ edit_review_form() }}'))
        assert doc('#review-edit-form').length == 1
        assert doc('p.req').length == 1
        for name in ReviewForm().fields.keys():
            assert doc('[name=%s]' % name).length == 1
