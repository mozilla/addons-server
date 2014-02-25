from nose.tools import eq_

import jingo
from pyquery import PyQuery as pq

from addons.models import Addon
from amo.urlresolvers import reverse
from reviews.models import ReviewFlag
from reviews.forms import ReviewForm


def setup():
    jingo.load_helpers()


def render(s, context={}):
    t = jingo.env.from_string(s)
    return t.render(**context)


def test_stars():
    s = render('{{ num|stars }}', {'num': None})
    eq_(s, 'Not yet rated')

    doc = pq(render('{{ num|stars }}', {'num': 1}))
    msg = 'Rated 1 out of 5 stars'
    eq_(doc.attr('class'), 'stars stars-1')
    eq_(doc.attr('title'), msg)
    eq_(doc.text(), msg)


def test_stars_details_page():
    doc = pq(render('{{ num|stars(large=True) }}', {'num': 2}))
    eq_(doc('.stars').attr('class'), 'stars large stars-2')


def test_stars_max():
    doc = pq(render('{{ num|stars }}', {'num': 5.3}))
    eq_(doc.attr('class'), 'stars stars-5')


def test_reviews_link():
    a = Addon(average_rating=4, total_reviews=37, id=1, type=1, slug='xx')
    s = render('{{ reviews_link(myaddon) }}', {'myaddon': a})
    eq_(pq(s)('strong').text(), '37 reviews')

    # without collection uuid
    eq_(pq(s)('a').attr('href'), '/addon/xx/#reviews')

    # with collection uuid
    myuuid = 'f19a8822-1ee3-4145-9440-0a3640201fe6'
    s = render('{{ reviews_link(myaddon, myuuid) }}', {'myaddon': a,
                                                       'myuuid': myuuid})
    eq_(pq(s)('a').attr('href'),
        '/addon/xx/?collection_uuid=%s#reviews' % myuuid)

    z = Addon(average_rating=0, total_reviews=0, id=1, type=1, slug='xx')
    s = render('{{ reviews_link(myaddon) }}', {'myaddon': z})
    eq_(pq(s)('strong').text(), 'Not yet rated')

    # with link
    u = reverse('addons.reviews.list', args=['xx'])
    s = render('{{ reviews_link(myaddon, link_to_list=True) }}',
               {'myaddon': a})
    eq_(pq(s)('a').attr('href'), u)


def test_mobile_reviews_link():
    s = lambda a: pq(render('{{ mobile_reviews_link(myaddon) }}',
                     {'myaddon': a}))

    a = Addon(total_reviews=0, id=1, type=1, slug='xx')
    doc = s(a)
    eq_(doc('a').attr('href'), reverse('addons.reviews.add', args=['xx']))

    u = reverse('addons.reviews.list', args=['xx'])

    a = Addon(average_rating=4, total_reviews=37, id=1, type=1, slug='xx')
    doc = s(a)
    eq_(doc('a').attr('href'), u)
    eq_(doc('a').text(), 'Rated 4 out of 5 stars See All 37 Reviews')

    a = Addon(average_rating=4, total_reviews=1, id=1, type=1, slug='xx')
    doc = s(a)
    doc.remove('div')
    eq_(doc('a').attr('href'), u)
    eq_(doc('a').text(), 'See All Reviews')


def test_report_review_popup():
    doc = pq(render('{{ report_review_popup() }}'))
    eq_(doc('.popup.review-reason').length, 1)
    for flag, text in ReviewFlag.FLAGS:
        eq_(doc('li a[href$=%s]' % flag).text(), text)
    eq_(doc('form input[name=note]').length, 1)


def test_edit_review_form():
    doc = pq(render('{{ edit_review_form() }}'))
    eq_(doc('#review-edit-form').length, 1)
    eq_(doc('p.req').length, 1)
    for name in ReviewForm().fields.keys():
        eq_(doc('[name=%s]' % name).length, 1)
