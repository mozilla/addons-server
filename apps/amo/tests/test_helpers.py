# -*- coding: utf-8 -*-
from datetime import datetime
import os

from django.conf import settings
from django.core import mail
from django.utils import encoding

import jingo
from mock import Mock, patch
from nose.tools import eq_
from pyquery import PyQuery

import test_utils

import amo
from amo import urlresolvers, utils, helpers
from amo.utils import ImageCheck
from versions.models import License


def render(s, context={}):
    t = jingo.env.from_string(s)
    return t.render(**context)


def test_strip_html():
    eq_('Hey Brother!', render('{{ "Hey <b>Brother!</b>"|strip_html }}'))


def test_currencyfmt():
    eq_(helpers.currencyfmt(None, 'USD'), '')
    eq_(helpers.currencyfmt(5, 'USD'), '$5.00')


def test_strip_html_none():
    eq_('', render('{{ a|strip_html }}', {'a': None}))
    eq_('', render('{{ a|strip_html(True) }}', {'a': None}))


def test_strip_controls():
    """We want control codes like \x0c to disappear."""
    eq_('I ove you', render('{{ "I \x0cove you"|strip_controls }}'))


def test_finalize():
    """We want None to show up as ''.  We do this in JINJA_CONFIG."""
    eq_('', render('{{ x }}', {'x': None}))


def test_slugify_spaces():
    """We want slugify to preserve spaces, but not at either end."""
    eq_(utils.slugify(' b ar '), 'b-ar')
    eq_(utils.slugify(' b ar ', spaces=True), 'b ar')
    eq_(utils.slugify(' b  ar ', spaces=True), 'b  ar')


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

    # Check the dirty unicodes.
    request.APP = amo.FIREFOX
    s = render('{{ page_title(x) }}',
               {'request': request,
                'x': encoding.smart_str(u'\u05d0\u05d5\u05e1\u05e3')})


class TestBreadcrumbs(object):

    def setUp(self):
        self.req_noapp = Mock()
        self.req_noapp.APP = None
        self.req_app = Mock()
        self.req_app.APP = amo.FIREFOX

    def test_no_app(self):
        s = render('{{ breadcrumbs() }}', {'request': self.req_noapp})
        doc = PyQuery(s)
        crumbs = doc('li>a')
        eq_(len(crumbs), 1)
        eq_(crumbs.text(), 'Add-ons')
        eq_(crumbs.attr('href'), urlresolvers.reverse('home'))

    def test_with_app(self):
        s = render('{{ breadcrumbs() }}', {'request': self.req_app})
        doc = PyQuery(s)
        crumbs = doc('li>a')
        eq_(len(crumbs), 1)
        eq_(crumbs.text(), 'Add-ons for Firefox')
        eq_(crumbs.attr('href'), urlresolvers.reverse('home'))

    def test_no_add_default(self):
        s = render('{{ breadcrumbs(add_default=False) }}',
                   {'request': self.req_app})
        eq_(len(s), 0)

    def test_items(self):
        s = render("""{{ breadcrumbs([('/foo', 'foo'),
                                      ('/bar', 'bar')],
                                     add_default=False) }}'""",
                   {'request': self.req_app})
        doc = PyQuery(s)
        crumbs = doc('li>a')
        eq_(len(crumbs), 2)
        eq_(crumbs.eq(0).text(), 'foo')
        eq_(crumbs.eq(0).attr('href'), '/foo')
        eq_(crumbs.eq(1).text(), 'bar')
        eq_(crumbs.eq(1).attr('href'), '/bar')

    def test_items_with_default(self):
        s = render("""{{ breadcrumbs([('/foo', 'foo'),
                                      ('/bar', 'bar')]) }}'""",
                   {'request': self.req_app})
        doc = PyQuery(s)
        crumbs = doc('li>a')
        eq_(len(crumbs), 3)
        eq_(crumbs.eq(1).text(), 'foo')
        eq_(crumbs.eq(1).attr('href'), '/foo')
        eq_(crumbs.eq(2).text(), 'bar')
        eq_(crumbs.eq(2).attr('href'), '/bar')

    def test_truncate(self):
        s = render("""{{ breadcrumbs([('/foo', 'abcd efghij'),],
                                     crumb_size=5) }}'""",
                   {'request': self.req_app})
        doc = PyQuery(s)
        crumbs = doc('li>a')
        eq_('abcd ...', crumbs.eq(1).text())

    def test_xss(self):
        s = render("{{ breadcrumbs([('/foo', '<script>')]) }}",
                   {'request': self.req_app})
        assert '&lt;script&gt;' in s, s
        assert '<script>' not in s


@patch('amo.helpers.urlresolvers.reverse')
def test_url(mock_reverse):
    render('{{ url("viewname", 1, z=2) }}')
    mock_reverse.assert_called_with('viewname', args=(1,), kwargs={'z': 2},
                                    add_prefix=True)

    s = render('{{ url("viewname", 1, z=2, host="myhost") }}')
    mock_reverse.assert_called_with('viewname', args=(1,), kwargs={'z': 2},
                                    add_prefix=True)


def test_url_src():
    s = render('{{ url("addons.detail", "a3615", src="xxx") }}')
    assert s.endswith('?src=xxx')


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

    # Removing a query
    s = render('{{ base_query|urlparams(x=None) }}', c)
    eq_(s, url)


def test_urlparams_unicode():
    url = u'/xx?evil=reco\ufffd\ufffd\ufffd\u02f5'
    utils.urlparams(url)


def test_isotime():
    time = datetime(2009, 12, 25, 10, 11, 12)
    s = render('{{ d|isotime }}', {'d': time})
    eq_(s, '2009-12-25T18:11:12Z')
    s = render('{{ d|isotime }}', {'d': None})
    eq_(s, '')


def test_epoch():
    time = datetime(2009, 12, 25, 10, 11, 12)
    s = render('{{ d|epoch }}', {'d': time})
    eq_(s, '1261764672')
    s = render('{{ d|epoch }}', {'d': None})
    eq_(s, '')


def test_locale_url():
    rf = test_utils.RequestFactory()
    request = rf.get('/de', SCRIPT_NAME='/z')
    prefixer = urlresolvers.Prefixer(request)
    urlresolvers.set_url_prefix(prefixer)
    s = render('{{ locale_url("mobile") }}')
    eq_(s, '/z/de/mobile')


def test_external_url():
    redirect_url = settings.REDIRECT_URL
    secretkey = settings.REDIRECT_SECRET_KEY
    settings.REDIRECT_URL = 'http://example.net'
    settings.REDIRECT_SECRET_KEY = 'sekrit'

    try:
        myurl = 'http://example.com'
        s = render('{{ "%s"|external_url }}' % myurl)
        eq_(s, urlresolvers.get_outgoing_url(myurl))
    finally:
        settings.REDIRECT_URL = redirect_url
        settings.REDIRECT_SECRET_KEY = secretkey


class TestLicenseLink(test_utils.TestCase):

    def test_license_link(self):
        mit = License.objects.create(
            name='MIT/X11 License', builtin=6, url='http://m.it')
        copyright = License.objects.create(
            name='All Rights Reserved', icons='copyr', builtin=7)
        cc = License.objects.create(
            name='Creative Commons', url='http://cre.at', builtin=8,
            some_rights=True, icons='cc-attrib cc-noncom cc-share')
        cc.save()
        expected = {
            mit: (
                '<ul class="license"><li class="text">'
                '<a href="http://m.it">MIT/X11 License</a></li></ul>'),
            copyright: (
                '<ul class="license"><li class="icon copyr"></li>'
                '<li class="text">All Rights Reserved</li></ul>'),
            cc: (
                '<ul class="license"><li class="icon cc-attrib"></li>'
                '<li class="icon cc-noncom"></li><li class="icon cc-share">'
                '</li><li class="text"><a href="http://cre.at" '
                'title="Creative Commons">Some rights reserved</a></li></ul>'),
        }
        for lic, ex in expected.items():
            s = render('{{ license_link(lic) }}', {'lic': lic})
            s = ''.join([s.strip() for s in s.split('\n')])
            eq_(s, ex)

    def test_license_link_xss(self):
        mit = License.objects.create(
            name='<script>', builtin=6, url='<script>')
        copyright = License.objects.create(
            name='<script>', icons='<script>', builtin=7)
        cc = License.objects.create(
            name='<script>', url='<script>', builtin=8,
            some_rights=True, icons='<script> cc-noncom cc-share')
        cc.save()
        expected = {
            mit: (
                '<ul class="license"><li class="text">'
                '<a href="&lt;script&gt;">&lt;script&gt;</a></li></ul>'),
            copyright: (
                '<ul class="license"><li class="icon &lt;script&gt;"></li>'
                '<li class="text">&lt;script&gt;</li></ul>'),
            cc: (
                '<ul class="license"><li class="icon &lt;script&gt;"></li>'
                '<li class="icon cc-noncom"></li><li class="icon cc-share">'
                '</li><li class="text"><a href="&lt;script&gt;" '
                'title="&lt;script&gt;">Some rights reserved</a></li></ul>'),
        }
        for lic, ex in expected.items():
            s = render('{{ license_link(lic) }}', {'lic': lic})
            s = ''.join([s.strip() for s in s.split('\n')])
            eq_(s, ex)


class AbuseBase:
    @patch('captcha.fields.ReCaptchaField.clean')
    def test_abuse_anonymous(self, clean):
        clean.return_value = ""
        self.client.post(self.full_page, {'text': 'spammy'})
        eq_(len(mail.outbox), 1)
        assert 'spammy' in mail.outbox[0].body

    def test_abuse_anonymous_fails(self):
        r = self.client.post(self.full_page, {'text': 'spammy'})
        assert 'recaptcha' in r.context['abuse_form'].errors

    def test_abuse_logged_in(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.client.post(self.full_page, {'text': 'spammy'})
        eq_(len(mail.outbox), 1)
        assert 'spammy' in mail.outbox[0].body


class AbuseDisabledBase:
    def test_abuse_fails_anonymous(self):
        r = self.client.get(self.inline_page)
        doc = PyQuery(r.content)
        assert not doc("fieldset.abuse")

        res = self.client.post(self.full_page, {'text': 'spammy'})
        eq_(res.status_code, 404)

    def test_abuse_fails_logged_in(self):
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.get(self.inline_page)
        doc = PyQuery(r.content)
        assert not doc("fieldset.abuse")

        res = self.client.post(self.full_page)
        eq_(res.status_code, 404)


def get_image_path(name):
    return os.path.join(settings.ROOT, 'apps', 'amo', 'tests', 'images', name)


class TestAnimatedImages(test_utils.TestCase):

    def test_animated_images(self):
        img = ImageCheck(open(get_image_path('animated.png')))
        assert img.is_animated()
        img = ImageCheck(open(get_image_path('non-animated.png')))
        assert not img.is_animated()

        img = ImageCheck(open(get_image_path('animated.gif')))
        assert img.is_animated()
        img = ImageCheck(open(get_image_path('non-animated.gif')))
        assert not img.is_animated()

    def test_junk(self):
        img = ImageCheck(open(__file__, 'rb'))
        assert not img.is_image()
        img = ImageCheck(open(get_image_path('non-animated.gif')))
        assert img.is_image()


def test_site_nav():
    r = Mock()
    r.APP = amo.FIREFOX
    assert 'id="site-nav"' in helpers.site_nav({'request': r})
