from datetime import datetime

from nose.tools import eq_

import jingo

import amo


def render(s, context={}):
    t = jingo.env.from_string(s)
    return t.render(**context)


def test_page_title():
    ctx = {'APP': amo.FIREFOX}
    title = 'Oh hai!'
    s = render('{{ page_title("%s") }}' % title, ctx)
    eq_(s, '%s :: Add-ons for Firefox' % title)
