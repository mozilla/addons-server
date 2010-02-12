from nose.tools import eq_
from mock import Mock, patch

import jingo

import amo


def render(s, context={}):
    t = jingo.env.from_string(s)
    return t.render(**context)


def test_page_title():
    request = Mock()
    request.APP = amo.FIREFOX
    title = 'Oh hai!'
    s = render('{{ page_title("%s") }}' % title, {'request': request})
    eq_(s, '%s :: Add-ons for Firefox' % title)


@patch('amo.helpers.urlresolvers.reverse')
def test_url(mock_reverse):
    render('{{ url("viewname", 1, z=2) }}')
    mock_reverse.assert_called_with('viewname', args=(1,), kwargs={'z': 2})


def test_urlparams():
    url = '/en-US/firefox/themes/category'
    c = {'base': url,
         'base_frag': url + '#hash',
         'base_query': url + '?x=y',
         'sort': 'name', 'frag': 'frag'}

    # Adding a query.
    s = render('{{ base_frag|urlparams(sort=sort) }}', c)
    eq_(s, '%s?sort=name#hash' % url)

    # Adding a fragment.
    s = render('{{ base|urlparams(frag) }}', c)
    eq_(s, '%s#frag' % url)

    # Replacing a fragment.
    s = render('{{ base_frag|urlparams(frag) }}', c)
    eq_(s, '%s#frag' % url)

    # Adding query and fragment.
    s = render('{{ base_frag|urlparams(frag, sort=sort) }}', c)
    eq_(s, '%s?sort=name#frag' % url)

    # Adding query with existing params.
    s = render('{{ base_query|urlparams(frag, sort=sort) }}', c)
    eq_(s, '%s?sort=name&x=y#frag' % url)

    # Replacing a query param.
    s = render('{{ base_query|urlparams(frag, x="z") }}', c)
    eq_(s, '%s?x=z#frag' % url)

    # Params with value of None get dropped.
    s = render('{{ base|urlparams(sort=None) }}', c)
    eq_(s, url)
