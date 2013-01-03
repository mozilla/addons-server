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
from mkt.developers import helpers
from files.models import File, Platform
from users.models import UserProfile
from versions.models import Version


def test_hub_page_title():
    translation.activate('en-US')
    request = Mock()
    request.APP = None
    addon = Mock()
    addon.name = 'name'
    ctx = {'request': request, 'addon': addon}

    title = 'Oh hai!'
    s1 = render('{{ hub_page_title("%s") }}' % title, ctx)
    s2 = render('{{ mkt_page_title("%s | Developers") }}' % title, ctx)
    eq_(s1, s2)

    s1 = render('{{ hub_page_title() }}', ctx)
    s2 = render('{{ mkt_page_title("Developers") }}', ctx)
    eq_(s1, s2)

    s1 = render('{{ hub_page_title("%s", addon) }}' % title, ctx)
    s2 = render('{{ mkt_page_title("%s | %s") }}' % (title, addon.name), ctx)
    eq_(s1, s2)


class TestNewDevBreadcrumbs(amo.tests.TestCase):

    def setUp(self):
        self.request = Mock()
        self.request.APP = None

    def test_no_args(self):
        s = render('{{ hub_breadcrumbs() }}', {'request': self.request})
        eq_(s, '')

    def test_with_items(self):
        s = render("""{{ hub_breadcrumbs(items=[('/foo', 'foo'),
                                                ('/bar', 'bar')]) }}'""",
                  {'request': self.request})
        crumbs = pq(s)('li')
        expected = [
            ('Home', reverse('home')),
            ('Developers', reverse('ecosystem.landing')),
            ('foo', '/foo'),
            ('bar', '/bar'),
        ]
        amo.tests.check_links(expected, crumbs, verify=False)

    def test_with_app(self):
        product = Mock()
        product.name = 'Steamcube'
        product.id = 9999
        product.app_slug = 'scube'
        product.type = amo.ADDON_WEBAPP
        s = render("""{{ hub_breadcrumbs(product) }}""",
                   {'request': self.request, 'product': product})
        crumbs = pq(s)('li')
        expected = [
            ('Home', reverse('home')),
            ('Developers', reverse('ecosystem.landing')),
            ('My Submissions', reverse('mkt.developers.apps')),
            ('Steamcube', None),
        ]
        amo.tests.check_links(expected, crumbs, verify=False)

    def test_with_app_and_items(self):
        product = Mock()
        product.name = 'Steamcube'
        product.id = 9999
        product.app_slug = 'scube'
        product.type = amo.ADDON_WEBAPP
        product.get_dev_url.return_value = reverse('mkt.developers.apps.edit',
                                                 args=[product.app_slug])
        s = render("""{{ hub_breadcrumbs(product,
                                         items=[('/foo', 'foo'),
                                                ('/bar', 'bar')]) }}""",
                   {'request': self.request, 'product': product})
        crumbs = pq(s)('li')
        expected = [
            ('Home', reverse('home')),
            ('Developers', reverse('ecosystem.landing')),
            ('My Submissions', reverse('mkt.developers.apps')),
            ('Steamcube', product.get_dev_url()),
            ('foo', '/foo'),
            ('bar', '/bar'),
        ]
        amo.tests.check_links(expected, crumbs, verify=False)


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


class TestDevAgreement(amo.tests.TestCase):

    def setUp(self):
        self.user = UserProfile()

    def test_none(self):
        with self.settings(DEV_AGREEMENT_LAST_UPDATED=None):
            eq_(helpers.dev_agreement_ok(self.user), True)

    def test_date_oops(self):
        with self.settings(DEV_AGREEMENT_LAST_UPDATED=('wat?')):
            eq_(helpers.dev_agreement_ok(self.user), True)

    def test_not_agreed(self):
        # The user has never agreed to it so in this case we don't need to
        # worry them about changes.
        self.user.update(read_dev_agreement=None)
        with self.settings(DEV_AGREEMENT_LAST_UPDATED=
                           self.days_ago(10).date()):
            eq_(helpers.dev_agreement_ok(self.user), True)

    def test_past_agreed(self):
        self.user.update(read_dev_agreement=self.days_ago(10))
        with self.settings(DEV_AGREEMENT_LAST_UPDATED=self.days_ago(5).date()):
            eq_(helpers.dev_agreement_ok(self.user), False)

    def test_not_past(self):
        self.user.update(read_dev_agreement=self.days_ago(5))
        with self.settings(DEV_AGREEMENT_LAST_UPDATED=
                           self.days_ago(10).date()):
            eq_(helpers.dev_agreement_ok(self.user), True)
