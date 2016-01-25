# -*- coding: utf-8 -*-
import urllib

from django.utils import translation

import pytest
from mock import Mock
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
from amo.tests.test_helpers import render
from addons.models import Addon
from devhub import helpers
from files.models import File
from versions.models import Version


pytestmark = pytest.mark.django_db


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
    assert s1 == s2

    s1 = render('{{ dev_page_title() }}', ctx)
    s2 = render('{{ page_title("Developer Hub") }}', ctx)
    assert s1 == s2

    s1 = render('{{ dev_page_title("%s", addon) }}' % title, ctx)
    s2 = render('{{ page_title("%s :: %s") }}' % (title, addon.name), ctx)
    assert s1 == s2


class TestDevBreadcrumbs(amo.tests.BaseTestCase):

    def setUp(self):
        super(TestDevBreadcrumbs, self).setUp()
        self.request = Mock()
        self.request.APP = None

    def test_no_args(self):
        s = render('{{ dev_breadcrumbs() }}', {'request': self.request})
        doc = pq(s)
        crumbs = doc('li')
        assert len(crumbs) == 2
        assert crumbs.text() == 'Developer Hub My Submissions'
        assert crumbs.eq(1).children('a') == []

    def test_no_args_with_default(self):
        s = render('{{ dev_breadcrumbs(add_default=True) }}',
                   {'request': self.request})
        doc = pq(s)
        crumbs = doc('li')
        assert crumbs.text() == 'Add-ons Developer Hub My Submissions'
        assert crumbs.eq(1).children('a').attr('href') == reverse('devhub.index')
        assert crumbs.eq(2).children('a') == []

    def test_with_items(self):
        s = render("""{{ dev_breadcrumbs(items=[('/foo', 'foo'),
                                                ('/bar', 'bar')]) }}'""",
                   {'request': self.request})
        doc = pq(s)
        crumbs = doc('li>a')
        assert len(crumbs) == 4
        assert crumbs.eq(2).text() == 'foo'
        assert crumbs.eq(2).attr('href') == '/foo'
        assert crumbs.eq(3).text() == 'bar'
        assert crumbs.eq(3).attr('href') == '/bar'

    def test_with_addon(self):
        addon = Mock()
        addon.name = 'Firebug'
        addon.id = 1843
        s = render("""{{ dev_breadcrumbs(addon) }}""",
                   {'request': self.request, 'addon': addon})
        doc = pq(s)
        crumbs = doc('li')
        assert crumbs.text() == 'Developer Hub My Submissions Firebug'
        assert crumbs.eq(1).text() == 'My Submissions'
        assert crumbs.eq(1).children('a').attr('href') == reverse('devhub.addons')
        assert crumbs.eq(2).text() == 'Firebug'
        assert crumbs.eq(2).children('a') == []

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
        assert len(crumbs) == 5
        assert crumbs.eq(2).text() == 'Firebug'
        assert crumbs.eq(2).children('a').attr('href') == addon.get_dev_url()
        assert crumbs.eq(3).text() == 'foo'
        assert crumbs.eq(3).children('a').attr('href') == '/foo'
        assert crumbs.eq(4).text() == 'bar'
        assert crumbs.eq(4).children('a').attr('href') == '/bar'


def test_summarize_validation():
    v = Mock()
    v.errors = 1
    v.warnings = 1
    assert render('{{ summarize_validation(validation) }}', {'validation': v}) == u'1 error, 1 warning'
    v.errors = 2
    assert render('{{ summarize_validation(validation) }}', {'validation': v}) == u'2 errors, 1 warning'
    v.warnings = 2
    assert render('{{ summarize_validation(validation) }}', {'validation': v}) == u'2 errors, 2 warnings'


def test_log_action_class():
    v = Mock()
    for k, v in amo.LOG_BY_ID.iteritems():
        if v.action_class is not None:
            cls = 'action-' + v.action_class
        else:
            cls = ''
        assert render('{{ log_action_class(id) }}', {'id': v.id}) == cls


class TestDisplayUrl(amo.tests.BaseTestCase):

    def setUp(self):
        super(TestDisplayUrl, self).setUp()
        self.raw_url = u'http://host/%s' % 'フォクすけといっしょ'.decode('utf8')

    def test_utf8(self):
        url = urllib.quote(self.raw_url.encode('utf8'))
        assert render('{{ url|display_url }}', {'url': url}) == self.raw_url

    def test_unicode(self):
        url = urllib.quote(self.raw_url.encode('utf8'))
        url = unicode(url, 'utf8')
        assert render('{{ url|display_url }}', {'url': url}) == self.raw_url

    def test_euc_jp(self):
        url = urllib.quote(self.raw_url.encode('euc_jp'))
        assert render('{{ url|display_url }}', {'url': url}) == self.raw_url


class TestDevFilesStatus(amo.tests.TestCase):

    def setUp(self):
        super(TestDevFilesStatus, self).setUp()
        self.addon = Addon.objects.create(type=1, status=amo.STATUS_UNREVIEWED)
        self.version = Version.objects.create(addon=self.addon)
        self.file = File.objects.create(version=self.version,
                                        platform=amo.PLATFORM_ALL.id,
                                        status=amo.STATUS_UNREVIEWED)

    def expect(self, expected):
        cnt, msg = helpers.dev_files_status([self.file], self.addon)[0]
        assert cnt == 1
        assert msg == unicode(expected)

    def test_unreviewed_lite(self):
        self.addon.status = amo.STATUS_LITE
        self.file.status = amo.STATUS_UNREVIEWED
        self.expect(Addon.STATUS_CHOICES[amo.STATUS_UNREVIEWED])

    def test_unreviewed_public(self):
        self.addon.status = amo.STATUS_PUBLIC
        self.file.status = amo.STATUS_UNREVIEWED
        self.expect(Addon.STATUS_CHOICES[amo.STATUS_NOMINATED])

    def test_unreviewed_nominated(self):
        self.addon.status = amo.STATUS_NOMINATED
        self.file.status = amo.STATUS_UNREVIEWED
        self.expect(Addon.STATUS_CHOICES[amo.STATUS_NOMINATED])

    def test_unreviewed_lite_and_nominated(self):
        self.addon.status = amo.STATUS_LITE_AND_NOMINATED
        self.file.status = amo.STATUS_UNREVIEWED
        self.expect(Addon.STATUS_CHOICES[amo.STATUS_NOMINATED])

    def test_reviewed_lite(self):
        self.addon.status = amo.STATUS_LITE
        self.file.status = amo.STATUS_LITE
        self.expect(File.STATUS_CHOICES[amo.STATUS_LITE])

    def test_reviewed_public(self):
        self.addon.status = amo.STATUS_PUBLIC
        self.file.status = amo.STATUS_PUBLIC
        self.expect(File.STATUS_CHOICES[amo.STATUS_PUBLIC])

    def test_disabled(self):
        self.addon.status = amo.STATUS_PUBLIC
        self.file.status = amo.STATUS_DISABLED
        self.expect(File.STATUS_CHOICES[amo.STATUS_DISABLED])
