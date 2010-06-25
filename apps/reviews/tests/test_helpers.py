from nose.tools import eq_

import jingo
from pyquery import PyQuery

from addons.models import Addon


def setup():
    jingo.load_helpers()


def render(s, context={}):
    t = jingo.env.from_string(s)
    return t.render(**context)


def test_stars():
    s = render('{{ num|stars }}', {'num': None})
    eq_(s, 'Not yet rated')

    doc = PyQuery(render('{{ num|stars }}', {'num': 1}))
    msg = 'Rated 1 out of 5 stars'
    eq_(doc.attr('class'), 'stars stars-1')
    eq_(doc.attr('title'), msg)
    eq_(doc.text(), msg)


def test_stars_max():
    doc = PyQuery(render('{{ num|stars }}', {'num': 5.3}))
    eq_(doc.attr('class'), 'stars stars-5')


def test_reviews_link():
    a = Addon(average_rating=4, total_reviews=37, id=1)
    s = render('{{ myaddon|reviews_link }}', {'myaddon': a})
    eq_(PyQuery(s)('strong').text(), '37 reviews')

    # without collection uuid
    eq_(PyQuery(s)('a').attr('href'), '/addon/1/#reviews')

    # with collection uuid
    myuuid = 'f19a8822-1ee3-4145-9440-0a3640201fe6'
    s = render('{{ myaddon|reviews_link(myuuid) }}', {'myaddon': a,
                                                      'myuuid': myuuid})
    eq_(PyQuery(s)('a').attr('href'),
        '/addon/1/?collection_uuid=%s#reviews' % myuuid)

    z = Addon(average_rating=0, total_reviews=0, id=1)
    s = render('{{ myaddon|reviews_link }}', {'myaddon': z})
    eq_(PyQuery(s)('strong').text(), 'Not yet rated')
