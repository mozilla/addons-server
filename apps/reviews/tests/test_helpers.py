from nose.tools import eq_

import jingo


def render(s, context={}):
    t = jingo.env.from_string(s)
    return t.render(**context)


def test_stars():
    s = render('{{ num|stars }}', {'num': None})
    eq_(s, 'Not yet rated')

    s = render('{{ num|stars }}', {'num': 1})
    msg = 'Rated 1 out of 5 stars'
    eq_(s, '<span class="stars stars-1" title="{0}">{0}</span>'.format(msg))
