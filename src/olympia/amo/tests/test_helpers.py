# -*- coding: utf-8 -*-
import mimetypes
import os
from datetime import datetime, timedelta
from urlparse import urljoin

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import RequestFactory
from django.test.utils import override_settings
from django.utils.encoding import force_bytes

import jingo
import pytest
from mock import Mock, patch
from pyquery import PyQuery

import olympia
from olympia import amo
from olympia.amo.tests import TestCase
from olympia.amo import urlresolvers, utils, helpers
from olympia.amo.utils import ImageCheck
from olympia.versions.models import License


ADDONS_TEST_FILES = os.path.join(
    os.path.dirname(olympia.__file__),
    'devhub', 'tests', 'addons')


pytestmark = pytest.mark.django_db


def render(s, context=None):
    if context is None:
        context = {}
    t = jingo.get_env().from_string(s)
    return t.render(context)


def test_strip_html():
    assert 'Hey Brother!' == render('{{ "Hey <b>Brother!</b>"|strip_html }}')


def test_currencyfmt():
    assert helpers.currencyfmt(None, 'USD') == ''
    assert helpers.currencyfmt(5, 'USD') == '$5.00'
    assert helpers.currencyfmt('12', 'USD') == '$12.00'


def test_strip_html_none():
    assert '' == render('{{ a|strip_html }}', {'a': None})
    assert '' == render('{{ a|strip_html(True) }}', {'a': None})


def test_strip_controls():
    # We want control codes like \x0c to disappear.
    assert 'I ove you' == helpers.strip_controls('I \x0cove you')


def test_finalize():
    """We want None to show up as ''.  We do this in JINJA_CONFIG."""
    assert '' == render('{{ x }}', {'x': None})


def test_slugify_spaces():
    """We want slugify to preserve spaces, but not at either end."""
    assert utils.slugify(' b ar ') == 'b-ar'
    assert utils.slugify(' b ar ', spaces=True) == 'b ar'
    assert utils.slugify(' b  ar ', spaces=True) == 'b  ar'


def test_page_title():
    request = Mock()
    request.APP = amo.THUNDERBIRD
    title = 'Oh hai!'
    s = render('{{ page_title("%s") }}' % title, {'request': request})
    assert s == '%s :: Add-ons for Thunderbird' % title

    # pages without app should show a default
    request.APP = None
    s = render('{{ page_title("%s") }}' % title, {'request': request})
    assert s == '%s :: Add-ons' % title

    # Check the dirty unicodes.
    request.APP = amo.FIREFOX
    s = render('{{ page_title(x) }}',
               {'request': request,
                'x': force_bytes(u'\u05d0\u05d5\u05e1\u05e3')})


def test_page_title_markup():
    """If the title passed to page_title is a jinja2 Markup object, don't cast
    it back to a string or it'll get double escaped. See issue #1062."""
    request = Mock()
    request.APP = amo.FIREFOX
    # Markup isn't double escaped.
    res = render(
        '{{ page_title("{0}"|fe("It\'s all text")) }}', {'request': request})
    assert res == 'It&#39;s all text :: Add-ons for Firefox'


def test_template_escaping():
    """Test that tests various formatting scenarios we're using in our
    templates and makes sure they're working as expected.
    """
    # Simple HTML in a translatable string
    expected = '<a href="...">This is a test</a>'
    assert render('{{ _(\'<a href="...">This is a test</a>\') }}') == expected

    # Simple HTML in a translatable string, with |fe works as expected
    expected = '<a href="...">This is a test</a>'
    original = '{{ _(\'<a href="...">{0}</a>\')|fe(\'This is a test\') }}'
    assert render(original) == expected

    # |f does not mark the resulting string as "safe" thus autoescaping
    # set's in
    expected = '&lt;a href=&#34;...&#34;&gt;This is a test&lt;/a&gt;'
    original = '{{ _(\'<a href="...">{0}</a>\')|f(\'This is a test\') }}'
    assert render(original) == expected

    # if an explicit |safe before |f is applied the output is still unsafe
    # and will be autoescaped. Use |fe for that.
    expected = '&lt;a href=&#34;...&#34;&gt;This is a test&lt;/a&gt;'
    original = '{{ _(\'<a href="...">{0}</a>\')|safe|f(\'This is a test\') }}'
    assert render(original) == expected

    # |safe after the |f marks the whole formatted string as safe though
    # and autoescaping won't be applied anymore.
    # Please note that this does not escape the arguments of |f!
    expected = '<a href="...">This is a test</a>'
    original = '{{ _(\'<a href="...">{0}</a>\')|f(\'This is a test\')|safe }}'
    assert render(original) == expected

    # Various tests for gettext related helpers and make sure they work
    # properly just as `_()` does.
    expected = '<b>5 users</b>'
    assert render(
        '{{ ngettext(\'<b>{0} user</b>\', \'<b>{0} users</b>\', 2)|fe(5) }}'
    ) == expected

    # You could also mark the whole output as |safe but note that this
    # does not escape the arguments of |f!
    expected = '<b>5 users</b>'
    assert render(
        '{{ ngettext(\'<b>{0} user</b>\', \'<b>{0} users</b>\', 2)'
        '|f(5)|safe }}'
    ) == expected

    # and now only with |f it get's escaped again
    expected = '&lt;b&gt;5 users&lt;/b&gt;'
    assert render(
        '{{ ngettext(\'<b>{0} user</b>\', \'<b>{0} users</b>\', 2)|f(5) }}'
    ) == expected


@patch('olympia.amo.helpers.urlresolvers.reverse')
def test_url(mock_reverse):
    render('{{ url("viewname", 1, z=2) }}')
    mock_reverse.assert_called_with('viewname', args=(1,), kwargs={'z': 2},
                                    add_prefix=True)

    render('{{ url("viewname", 1, z=2, host="myhost") }}')
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
    assert s == '%s?sort=name#hash' % url

    # Adding a fragment.
    s = render('{{ base|urlparams(frag) }}', c)
    assert s == '%s#frag' % url

    # Replacing a fragment.
    s = render('{{ base_frag|urlparams(frag) }}', c)
    assert s == '%s#frag' % url

    # Adding query and fragment.
    s = render('{{ base_frag|urlparams(frag, sort=sort) }}', c)
    assert s == '%s?sort=name#frag' % url

    # Adding query with existing params.
    s = render('{{ base_query|urlparams(frag, sort=sort) }}', c)
    amo.tests.assert_url_equal(s, '%s?sort=name&amp;x=y#frag' % url)

    # Replacing a query param.
    s = render('{{ base_query|urlparams(frag, x="z") }}', c)
    assert s == '%s?x=z#frag' % url

    # Params with value of None get dropped.
    s = render('{{ base|urlparams(sort=None) }}', c)
    assert s == url

    # Removing a query
    s = render('{{ base_query|urlparams(x=None) }}', c)
    assert s == url


def test_urlparams_unicode():
    url = u'/xx?evil=reco\ufffd\ufffd\ufffd\u02f5'
    utils.urlparams(url)


def test_urlparams_returns_safe_string():
    s = render('{{ "https://foo.com/"|urlparams(param="help+me") }}', {})
    assert s == 'https://foo.com/?param=help%2Bme'

    s = render(u'{{ "https://foo.com/"|urlparams(param="obiwankénobi") }}', {})
    assert s == 'https://foo.com/?param=obiwank%C3%A9nobi'

    s = render(u'{{ "https://foo.com/"|urlparams(param=42) }}', {})
    assert s == 'https://foo.com/?param=42'

    s = render(u'{{ "https://foo.com/"|urlparams(param="") }}', {})
    assert s == 'https://foo.com/?param='

    s = render('{{ "https://foo.com/"|urlparams(param="help%2Bme") }}', {})
    assert s == 'https://foo.com/?param=help%2Bme'

    s = render('{{ "https://foo.com/"|urlparams(param="a%20b") }}', {})
    assert s == 'https://foo.com/?param=a+b'

    s = render('{{ "https://foo.com/"|urlparams(param="%AAA") }}', {})
    assert s == 'https://foo.com/?param=%AAA'


def test_isotime():
    time = datetime(2009, 12, 25, 10, 11, 12)
    s = render('{{ d|isotime }}', {'d': time})
    assert s == '2009-12-25T10:11:12Z'
    s = render('{{ d|isotime }}', {'d': None})
    assert s == ''


def test_epoch():
    time = datetime(2009, 12, 25, 10, 11, 12)
    s = render('{{ d|epoch }}', {'d': time})
    assert s == '1261735872'
    s = render('{{ d|epoch }}', {'d': None})
    assert s == ''


def test_locale_url():
    rf = RequestFactory()
    request = rf.get('/de', SCRIPT_NAME='/z')
    prefixer = urlresolvers.Prefixer(request)
    urlresolvers.set_url_prefix(prefixer)
    s = render('{{ locale_url("mobile") }}')
    assert s == '/z/de/mobile'


def test_external_url():
    redirect_url = settings.REDIRECT_URL
    secretkey = settings.REDIRECT_SECRET_KEY
    settings.REDIRECT_URL = 'http://example.net'
    settings.REDIRECT_SECRET_KEY = 'sekrit'

    try:
        myurl = 'http://example.com'
        s = render('{{ "%s"|external_url }}' % myurl)
        assert s == urlresolvers.get_outgoing_url(myurl)
    finally:
        settings.REDIRECT_URL = redirect_url
        settings.REDIRECT_SECRET_KEY = secretkey


@patch('olympia.amo.helpers.urlresolvers.get_outgoing_url')
def test_linkify_bounce_url_callback(mock_get_outgoing_url):
    mock_get_outgoing_url.return_value = 'bar'

    res = urlresolvers.linkify_bounce_url_callback({'href': 'foo'})

    # Make sure get_outgoing_url was called.
    assert res == {'href': 'bar'}
    mock_get_outgoing_url.assert_called_with('foo')


@patch('olympia.amo.helpers.urlresolvers.linkify_bounce_url_callback')
def test_linkify_with_outgoing_text_links(mock_linkify_bounce_url_callback):
    def side_effect(attrs, new=False):
        attrs['href'] = 'bar'
        return attrs

    mock_linkify_bounce_url_callback.side_effect = side_effect

    # Without nofollow.
    res = urlresolvers.linkify_with_outgoing('a text http://example.com link',
                                             nofollow=False)
    assert res == 'a text <a href="bar">http://example.com</a> link'

    # With nofollow (default).
    res = urlresolvers.linkify_with_outgoing('a text http://example.com link')
    # Use PyQuery because the attributes could be rendered in any order.
    doc = PyQuery(res)
    assert doc('a[href="bar"][rel="nofollow"]')[0].text == 'http://example.com'

    res = urlresolvers.linkify_with_outgoing('a text http://example.com link',
                                             nofollow=True)
    assert doc('a[href="bar"][rel="nofollow"]')[0].text == 'http://example.com'


@patch('olympia.amo.helpers.urlresolvers.linkify_bounce_url_callback')
def test_linkify_with_outgoing_markup_links(mock_linkify_bounce_url_callback):
    def side_effect(attrs, new=False):
        attrs['href'] = 'bar'
        return attrs

    mock_linkify_bounce_url_callback.side_effect = side_effect

    # Without nofollow.
    res = urlresolvers.linkify_with_outgoing(
        'a markup <a href="http://example.com">link</a> with text',
        nofollow=False)
    assert res == 'a markup <a href="bar">link</a> with text'

    # With nofollow (default).
    res = urlresolvers.linkify_with_outgoing(
        'a markup <a href="http://example.com">link</a> with text')
    # Use PyQuery because the attributes could be rendered in any order.
    doc = PyQuery(res)
    assert doc('a[href="bar"][rel="nofollow"]')[0].text == 'link'

    res = urlresolvers.linkify_with_outgoing(
        'a markup <a href="http://example.com">link</a> with text',
        nofollow=True)
    assert doc('a[href="bar"][rel="nofollow"]')[0].text == 'link'


class TestLicenseLink(TestCase):

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
            res = render('{{ license_link(lic) }}', {'lic': lic})
            res = ''.join([s.strip() for s in res.split('\n')])
            assert res == ex

    def test_theme_license_link(self):
        s = render('{{ license_link(lic) }}', {'lic': amo.LICENSE_COPYRIGHT})

        ul = PyQuery(s)('.license')
        assert ul.find('.icon').length == 1
        assert ul.find('.icon.copyr').length == 1

        text = ul.find('.text')
        assert text.find('a').length == 0
        assert text.text() == 'All Rights Reserved'

        s = render('{{ license_link(lic) }}', {'lic': amo.LICENSE_CC_BY_NC_SA})

        ul = PyQuery(s)('.license')
        assert ul.find('.icon').length == 3
        assert ul.find('.icon.cc-attrib').length == 1
        assert ul.find('.icon.cc-noncom').length == 1
        assert ul.find('.icon.cc-share').length == 1

        link = ul.find('.text a')
        assert link.find('a').length == 0
        assert link.text() == 'Some rights reserved'
        assert link.attr('href') == amo.LICENSE_CC_BY_NC_SA.url

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
            res = render('{{ license_link(lic) }}', {'lic': lic})
            res = ''.join([s.strip() for s in res.split('\n')])
            assert res == ex


def get_image_path(name):
    return os.path.join(
        settings.ROOT, 'src', 'olympia', 'amo', 'tests', 'images', name)


def get_uploaded_file(name):
    data = open(get_image_path(name)).read()
    return SimpleUploadedFile(name, data,
                              content_type=mimetypes.guess_type(name)[0])


def get_addon_file(name):
    return os.path.join(ADDONS_TEST_FILES, name)


class TestAnimatedImages(TestCase):

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


def test_jinja_trans_monkeypatch():
    # This tests the monkeypatch in manage.py that prevents localizers from
    # taking us down.
    render('{% trans come_on=1 %}% (come_on)s{% endtrans %}')
    render('{% trans come_on=1 %}%(come_on){% endtrans %}')
    render('{% trans come_on=1 %}%(come_on)z{% endtrans %}')


def test_absolutify():
    assert helpers.absolutify('/woo'), urljoin(settings.SITE_URL == '/woo')
    assert helpers.absolutify('https://addons.mozilla.org') == (
        'https://addons.mozilla.org')


def test_timesince():
    month_ago = datetime.now() - timedelta(days=30)
    assert helpers.timesince(month_ago) == u'1 month ago'
    assert helpers.timesince(None) == u''


def test_f():
    # This makes sure there's no UnicodeEncodeError when doing the string
    # interpolation.
    assert render(u'{{ "foo {0}"|f("baré") }}') == u'foo baré'


def test_inline_css(monkeypatch):
    jingo.load_helpers()
    env = jingo.get_env()
    t = env.from_string("{{ inline_css('zamboni/mobile', debug=True) }}")

    # Monkeypatch settings.LESS_BIN to not call the less compiler. We don't
    # need nor want it in tests.
    monkeypatch.setattr(settings, 'LESS_BIN', 'ls')
    # Monkeypatch jingo_minify.helpers.is_external to counter-effect the
    # autouse fixture in conftest.py.
    monkeypatch.setattr(amo.helpers, 'is_external', lambda css: False)
    s = t.render()

    assert 'background-image: url(/static/img/icons/stars.png);' in s


class TestStoragePath(TestCase):

    @override_settings(ADDONS_PATH=None, MEDIA_ROOT="/path/")
    def test_without_settings(self):
        del settings.ADDONS_PATH
        path = helpers.user_media_path('addons')
        assert path == '/path/addons'

    @override_settings(ADDONS_PATH="/another/path/")
    def test_with_settings(self):
        path = helpers.user_media_path('addons')
        assert path == '/another/path/'


class TestMediaUrl(TestCase):

    @override_settings(USERPICS_URL=None)
    def test_without_settings(self):
        del settings.USERPICS_URL
        settings.MEDIA_URL = '/mediapath/'
        url = helpers.user_media_url('userpics')
        assert url == '/mediapath/userpics/'


class TestIdToPath(TestCase):

    def test_with_1_digit(self):
        assert helpers.id_to_path(1) == '1/1/1'

    def test_with_2_digits(self):
        assert helpers.id_to_path(12) == '2/12/12'

    def test_with_3_digits(self):
        assert helpers.id_to_path(123) == '3/23/123'

    def test_with_many_digits(self):
        assert helpers.id_to_path(123456789) == '9/89/123456789'
