from django.utils import encoding, translation

import jingo
from mock import Mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
from amo.helpers import page_title
from amo.urlresolvers import reverse
from amo.tests.test_helpers import render


def test_dev_page_title():
    translation.activate('en-US')
    request = Mock()
    request.APP = None
    addon = Mock()
    addon.name = 'name'
    ctx = {'request': request, 'addon': addon}

    title = 'Oh hai!'
    s1 = render('{{ dev_page_title("%s") }}' % title, ctx)
    s2 = render('{{ page_title("%s :: Developer Hub") }}' % title, ctx)
    eq_(s1, s2)

    s1 = render('{{ dev_page_title() }}', ctx)
    s2 = render('{{ page_title("Developer Hub") }}', ctx)
    eq_(s1, s2)

    s1 = render('{{ dev_page_title("%s", addon) }}' % title, ctx)
    s2 = render('{{ page_title("%s :: %s") }}' % (title, addon.name), ctx)
    eq_(s1, s2)


def test_dev_breadcrumbs():
   request = Mock()
   request.APP = None

   # Default, ``add_default`` argument defaults to False.
   s = render('{{ dev_breadcrumbs() }}', {'request': request})
   doc = pq(s)
   crumbs = doc('li>a')
   eq_(len(crumbs), 2)
   eq_(crumbs.text(), 'Developer Hub My Add-ons')
   eq_(crumbs.attr('href'), reverse('devhub.index'))


   s = render('{{ dev_breadcrumbs(add_default=True) }}', {'request': request})
   doc = pq(s)
   crumbs = doc('li>a')
   eq_(len(crumbs), 3)
   eq_(crumbs.text(), 'Add-ons Developer Hub My Add-ons')
   eq_(crumbs.eq(1).attr('href'), reverse('devhub.index'))

   # N default, some items.
   s = render("""{{ dev_breadcrumbs(items=[('/foo', 'foo'),
                                           ('/bar', 'bar')]) }}'""",
              {'request': request})
   doc = pq(s)
   crumbs = doc('li>a')
   eq_(len(crumbs), 4)
   eq_(crumbs.eq(2).text(), 'foo')
   eq_(crumbs.eq(2).attr('href'), '/foo')
   eq_(crumbs.eq(3).text(), 'bar')
   eq_(crumbs.eq(3).attr('href'), '/bar')
