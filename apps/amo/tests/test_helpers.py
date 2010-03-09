from datetime import datetime

import jingo
from mock import Mock, patch
from nose.tools import eq_, assert_almost_equal, assert_raises

from pyquery import PyQuery
import test_utils

import amo
from amo import urlresolvers
from amo.helpers import wround


def render(s, context={}):
    t = jingo.env.from_string(s)
    return t.render(**context)


def test_finalize():
    """We want None to show up as ''.  We do this in JINJA_CONFIG."""
    eq_('', render('{{ x }}', {'x': None}))


def test_page_title():
    request = Mock()
    request.APP = amo.THUNDERBIRD
    title = 'Oh hai!'
    s = render('{{ page_title("%s") }}' % title, {'request': request})
    eq_(s, '%s :: Add-ons for Thunderbird' % title)

    # pages without app should show a default
    request.APP = None
    s = render('{{ page_title("%s") }}' % title, {'request': request})
    eq_(s, '%s :: Add-ons' % title)


def test_breadcrumbs():
    req_noapp = Mock()
    req_noapp.APP = None
    req_app = Mock()
    req_app.APP = amo.FIREFOX

    # default, no app
    s = render('{{ breadcrumbs() }}', {'request': req_noapp})
    doc = PyQuery(s)
    crumbs = doc('li>a')
    eq_(len(crumbs), 1)
    eq_(crumbs.text(), 'Add-ons')
    eq_(crumbs.attr('href'), urlresolvers.reverse('home'))

    # default, with app
    s = render('{{ breadcrumbs() }}', {'request': req_app})
    doc = PyQuery(s)
    crumbs = doc('li>a')
    eq_(len(crumbs), 1)
    eq_(crumbs.text(), 'Add-ons for Firefox')
    eq_(crumbs.attr('href'), urlresolvers.reverse('home'))

    # no default, no items => no breadcrumbs for you
    s = render('{{ breadcrumbs(add_default=False) }}', {'request': req_app})
    eq_(len(s), 0)

    # no default, some items
    s = render("""{{ breadcrumbs([('/foo', 'foo'),
                                  ('/bar', 'bar')],
                                 add_default=False) }}'""",
               {'request': req_app})
    doc = PyQuery(s)
    crumbs = doc('li>a')
    eq_(len(crumbs), 2)
    eq_(crumbs.eq(0).text(), 'foo')
    eq_(crumbs.eq(0).attr('href'), '/foo')
    eq_(crumbs.eq(1).text(), 'bar')
    eq_(crumbs.eq(1).attr('href'), '/bar')

    # default, some items
    s = render("""{{ breadcrumbs([('/foo', 'foo'),
                                  ('/bar', 'bar')]) }}'""",
               {'request': req_app})
    doc = PyQuery(s)
    crumbs = doc('li>a')
    eq_(len(crumbs), 3)
    eq_(crumbs.eq(1).text(), 'foo')
    eq_(crumbs.eq(1).attr('href'), '/foo')
    eq_(crumbs.eq(2).text(), 'bar')
    eq_(crumbs.eq(2).attr('href'), '/bar')


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
    eq_(s, '%s?sort=name&amp;x=y#frag' % url)

    # Replacing a query param.
    s = render('{{ base_query|urlparams(frag, x="z") }}', c)
    eq_(s, '%s?x=z#frag' % url)

    # Params with value of None get dropped.
    s = render('{{ base|urlparams(sort=None) }}', c)
    eq_(s, url)


def test_wround():
    # Invalid input formats.
    assert_raises(TypeError, wround, None)
    assert_raises(TypeError, wround, 'yadayada')
    assert_raises(TypeError, wround, '0')

    # Integers as well as floats should work.
    assert_almost_equal(wround(5, 2), 5)
    assert_almost_equal(wround(5.001, 2), 5)


def test_isotime():
    time = datetime(2009, 12, 25, 10, 11, 12)
    s = render('{{ d|isotime }}', {'d': time})
    eq_(s, '2009-12-25 18:11:12+0000')


def test_locale_url():
    rf = test_utils.RequestFactory()
    request = rf.get('/de', SCRIPT_NAME='/z')
    prefixer = urlresolvers.Prefixer(request)
    urlresolvers.set_url_prefix(prefixer)
    s = render('{{ locale_url("mobile") }}')
    eq_(s, '/z/de/mobile')
