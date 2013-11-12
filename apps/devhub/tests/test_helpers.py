# -*- coding: utf-8 -*-
import unittest
import urllib

from django.utils import translation

from mock import Mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
from amo.tests.test_helpers import render
from addons.models import Addon
from devhub import helpers
from files.models import File, Platform
from versions.models import Version


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


class TestDevBreadcrumbs(unittest.TestCase):

    def setUp(self):
        self.request = Mock()
        self.request.APP = None

    def test_no_args(self):
        s = render('{{ dev_breadcrumbs() }}', {'request': self.request})
        doc = pq(s)
        crumbs = doc('li')
        eq_(len(crumbs), 2)
        eq_(crumbs.text(), 'Developer Hub My Submissions')
        eq_(crumbs.eq(1).children('a'), [])

    def test_no_args_with_default(self):
        s = render('{{ dev_breadcrumbs(add_default=True) }}',
                   {'request': self.request})
        doc = pq(s)
        crumbs = doc('li')
        eq_(crumbs.text(), 'Add-ons Developer Hub My Submissions')
        eq_(crumbs.eq(1).children('a').attr('href'), reverse('devhub.index'))
        eq_(crumbs.eq(2).children('a'), [])

    def test_with_items(self):
        s = render("""{{ dev_breadcrumbs(items=[('/foo', 'foo'),
                                                ('/bar', 'bar')]) }}'""",
                  {'request': self.request})
        doc = pq(s)
        crumbs = doc('li>a')
        eq_(len(crumbs), 4)
        eq_(crumbs.eq(2).text(), 'foo')
        eq_(crumbs.eq(2).attr('href'), '/foo')
        eq_(crumbs.eq(3).text(), 'bar')
        eq_(crumbs.eq(3).attr('href'), '/bar')

    def test_with_addon(self):
        addon = Mock()
        addon.name = 'Firebug'
        addon.id = 1843
        s = render("""{{ dev_breadcrumbs(addon) }}""",
                   {'request': self.request, 'addon': addon})
        doc = pq(s)
        crumbs = doc('li')
        eq_(crumbs.text(), 'Developer Hub My Submissions Firebug')
        eq_(crumbs.eq(1).text(), 'My Submissions')
        eq_(crumbs.eq(1).children('a').attr('href'), reverse('devhub.addons'))
        eq_(crumbs.eq(2).text(), 'Firebug')
        eq_(crumbs.eq(2).children('a'), [])

    def test_with_addon_and_items(self):
        addon = Mock()
        addon.name = 'Firebug'
        addon.id = 1843
        addon.slug = 'fbug'
        addon.get_dev_url.return_value = reverse('devhub.addons.edit',
                                                   args=[addon.slug])
        s = render("""{{ dev_breadcrumbs(addon,
                                         items=[('/foo', 'foo'),
                                                ('/bar', 'bar')]) }}""",
                   {'request': self.request, 'addon': addon})
        doc = pq(s)
        crumbs = doc('li')
        eq_(len(crumbs), 5)
        eq_(crumbs.eq(2).text(), 'Firebug')
        eq_(crumbs.eq(2).children('a').attr('href'), addon.get_dev_url())
        eq_(crumbs.eq(3).text(), 'foo')
        eq_(crumbs.eq(3).children('a').attr('href'), '/foo')
        eq_(crumbs.eq(4).text(), 'bar')
        eq_(crumbs.eq(4).children('a').attr('href'), '/bar')


def test_summarize_validation():
    v = Mock()
    v.errors = 1
    v.warnings = 1
    eq_(render('{{ summarize_validation(validation) }}',
               {'validation': v}),
        u'1 error, 1 warning')
    v.errors = 2
    eq_(render('{{ summarize_validation(validation) }}',
               {'validation': v}),
        u'2 errors, 1 warning')
    v.warnings = 2
    eq_(render('{{ summarize_validation(validation) }}',
               {'validation': v}),
        u'2 errors, 2 warnings')


def test_log_action_class():
    v = Mock()
    for k, v in amo.LOG_BY_ID.iteritems():
        if v.action_class is not None:
            cls = 'action-' + v.action_class
        else:
            cls = ''
        eq_(render('{{ log_action_class(id) }}', {'id': v.id}), cls)


class TestDisplayUrl(unittest.TestCase):

    def setUp(self):
        self.raw_url = u'http://host/%s' % 'フォクすけといっしょ'.decode('utf8')

    def test_utf8(self):
        url = urllib.quote(self.raw_url.encode('utf8'))
        eq_(render('{{ url|display_url }}', {'url': url}),
            self.raw_url)

    def test_unicode(self):
        url = urllib.quote(self.raw_url.encode('utf8'))
        url = unicode(url, 'utf8')
        eq_(render('{{ url|display_url }}', {'url': url}),
            self.raw_url)

    def test_euc_jp(self):
        url = urllib.quote(self.raw_url.encode('euc_jp'))
        eq_(render('{{ url|display_url }}', {'url': url}),
            self.raw_url)


class TestDevFilesStatus(amo.tests.TestCase):

    def setUp(self):
        platform = Platform.objects.create(id=amo.PLATFORM_ALL.id)
        self.addon = Addon.objects.create(type=1, status=amo.STATUS_UNREVIEWED)
        self.version = Version.objects.create(addon=self.addon)
        self.file = File.objects.create(version=self.version,
                                        platform=platform,
                                        status=amo.STATUS_UNREVIEWED)

    def expect(self, expected):
        cnt, msg = helpers.dev_files_status([self.file], self.addon)[0]
        eq_(cnt, 1)
        eq_(msg, expected)

    def test_unreviewed_lite(self):
        self.addon.status = amo.STATUS_LITE
        self.file.status = amo.STATUS_UNREVIEWED
        self.expect(amo.STATUS_CHOICES[amo.STATUS_UNREVIEWED])

    def test_unreviewed_public(self):
        self.addon.status = amo.STATUS_PUBLIC
        self.file.status = amo.STATUS_UNREVIEWED
        self.expect(amo.STATUS_CHOICES[amo.STATUS_NOMINATED])

    def test_unreviewed_nominated(self):
        self.addon.status = amo.STATUS_NOMINATED
        self.file.status = amo.STATUS_UNREVIEWED
        self.expect(amo.STATUS_CHOICES[amo.STATUS_NOMINATED])

    def test_unreviewed_lite_and_nominated(self):
        self.addon.status = amo.STATUS_LITE_AND_NOMINATED
        self.file.status = amo.STATUS_UNREVIEWED
        self.expect(amo.STATUS_CHOICES[amo.STATUS_NOMINATED])

    def test_reviewed_lite(self):
        self.addon.status = amo.STATUS_LITE
        self.file.status = amo.STATUS_LITE
        self.expect(amo.STATUS_CHOICES[amo.STATUS_LITE])

    def test_reviewed_public(self):
        self.addon.status = amo.STATUS_PUBLIC
        self.file.status = amo.STATUS_PUBLIC
        self.expect(amo.STATUS_CHOICES[amo.STATUS_PUBLIC])

    def test_disabled(self):
        self.addon.status = amo.STATUS_PUBLIC
        self.file.status = amo.STATUS_DISABLED
        self.expect(amo.STATUS_CHOICES[amo.STATUS_DISABLED])
