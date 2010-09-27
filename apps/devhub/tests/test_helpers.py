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

    title = 'Oh hai!'
    s1 = render('{{ dev_page_title("%s") }}' % title, {'request': request})
    s2 = render('{{ page_title("%s :: Developer Hub") }}' % title,
                {'request': request})
    eq_(s1, s2)

    s1 = render('{{ dev_page_title() }}', {'request': request})
    s2 = render('{{ page_title("Developer Hub") }}', {'request': request})
    eq_(s1, s2)


def test_dev_breadcrumbs():
   request = Mock()
   request.APP = None

   # Default, ``add_default`` argument defaults to False.
   s = render('{{ dev_breadcrumbs() }}', {'request': request})
   doc = pq(s)
   crumbs = doc('li>a')
   eq_(len(crumbs), 1)
   eq_(crumbs.text(), 'Developer Hub')
   eq_(crumbs.attr('href'), reverse('devhub.index'))


   s = render('{{ dev_breadcrumbs(add_default=True) }}', {'request': request})
   doc = pq(s)
   crumbs = doc('li>a')
   eq_(len(crumbs), 2)
   eq_(crumbs.text(), 'Add-ons Developer Hub')
   eq_(crumbs.eq(1).attr('href'), reverse('devhub.index'))

   # N default, some items.
   s = render("""{{ dev_breadcrumbs([('/foo', 'foo'),
                                     ('/bar', 'bar')]) }}'""",
              {'request': request})
   doc = pq(s)
   crumbs = doc('li>a')
   eq_(len(crumbs), 3)
   eq_(crumbs.eq(1).text(), 'foo')
   eq_(crumbs.eq(1).attr('href'), '/foo')
   eq_(crumbs.eq(2).text(), 'bar')
   eq_(crumbs.eq(2).attr('href'), '/bar')
