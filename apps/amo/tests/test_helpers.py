from datetime import datetime

from nose.tools import eq_
from mock import patch

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


@patch('amo.helpers.urlresolvers.reverse')
def test_url(mock_reverse):
    render('{{ url("viewname", 1, z=2) }}')
    mock_reverse.assert_called_with('viewname', args=(1,), kwargs={'z': 2})
