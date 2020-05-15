# -*- coding: utf-8 -*-
import mimetypes
import os

from datetime import datetime, timedelta
from urllib.parse import urljoin
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import NoReverseMatch
from django.test.client import RequestFactory
from django.test.utils import override_settings
from django.utils.encoding import force_bytes

import pytest

from pyquery import PyQuery

import olympia

from olympia import amo
from olympia.amo import urlresolvers, utils
from olympia.amo.templatetags import jinja_helpers
from olympia.amo.tests import TestCase, reverse_ns
from olympia.amo.utils import ImageCheck


ADDONS_TEST_FILES = os.path.join(
    os.path.dirname(olympia.__file__),
    'devhub', 'tests', 'addons')


pytestmark = pytest.mark.django_db


def render(s, context=None):
    if context is None:
        context = {}
    t = utils.from_string(s)
    return t.render(context)


def test_strip_controls():
    # We want control codes like \x0c to disappear.
    assert 'I ove you' == jinja_helpers.strip_controls('I \x0cove you')


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
    title = 'Oh hai!'
    s = render('{{ page_title("%s") }}' % title, {'request': request})
    assert s == '%s :: Add-ons for Firefox' % title

    # Check the dirty unicodes.
    s = render('{{ page_title(x) }}',
               {'request': request,
                'x': force_bytes(u'\u05d0\u05d5\u05e1\u05e3')})


def test_page_title_markup():
    """If the title passed to page_title is a jinja2 Markup object, don't cast
    it back to a string or it'll get double escaped. See issue #1062."""
    request = Mock()
    # Markup isn't double escaped.
    res = render(
        '{{ page_title("{0}"|format_html("It\'s all text")) }}',
        {'request': request})
    assert res == 'It&#39;s all text :: Add-ons for Firefox'


def test_template_escaping():
    """Test that tests various formatting scenarios we're using in our
    templates and makes sure they're working as expected.
    """
    # Simple HTML in a translatable string
    expected = '<a href="...">This is a test</a>'
    assert render('{{ _(\'<a href="...">This is a test</a>\') }}') == expected

    # Simple HTML in a translatable string, with |format_html works
    # as expected
    expected = '<a href="...">This is a test</a>'
    original = (
        '{{ _(\'<a href="...">{0}</a>\')|format_html("This is a test") }}')
    assert render(original) == expected

    # The html provided in the translatable string won't be escaped
    # but all arguments are.
    expected = '<a href="...">This is a &lt;h1&gt;test&lt;/h1&gt;</a>'
    original = (
        '{{ _(\'<a href="...">{0}</a>\')|format_html('
        '"This is a <h1>test</h1>") }}')
    assert render(original) == expected

    # Unless marked explicitly as safe
    expected = '<a href="...">This is a <h1>test</h1></a>'
    original = (
        '{{ _(\'<a href="...">{0}</a>\')'
        '|format_html("This is a <h1>test</h1>"|safe) }}')
    assert render(original) == expected

    # Document how newstyle gettext behaves, everything that get's passed in
    # like that needs to be escaped!
    expected = '&lt;script&gt;&lt;/script&gt;'
    assert render('{{ _(foo) }}', {'foo': '<script></script>'}) != expected
    assert render(
        '{{ _(foo|escape) }}', {'foo': '<script></script>'}) == expected

    # Various tests for gettext related helpers and make sure they work
    # properly just as `_()` does.
    expected = '<b>5 users</b>'
    assert render(
        '{{ ngettext(\'<b>{0} user</b>\', \'<b>{0} users</b>\', 2)'
        '|format_html(5) }}'
    ) == expected

    # You could also mark the whole output as |safe but note that this
    # still escapes the arguments of |format_html unless explicitly
    # marked as safe
    expected = '<b>&lt;script&gt; users</b>'
    assert render(
        '{{ ngettext(\'<b>{0} user</b>\', \'<b>{0} users</b>\', 2)'
        '|format_html("<script>")|safe }}'
    ) == expected


@patch('olympia.amo.templatetags.jinja_helpers.urlresolvers.reverse')
def test_url(mock_reverse):
    render('{{ url("viewname", 1, z=2) }}')
    mock_reverse.assert_called_with('viewname', args=(1,), kwargs={'z': 2},
                                    add_prefix=True)

    render('{{ url("viewname", 1, z=2, host="myhost") }}')
    mock_reverse.assert_called_with('viewname', args=(1,), kwargs={'z': 2},
                                    add_prefix=True)


def test_url_src():
    fragment = render('{{ url("addons.detail", "a3615", src="xxx") }}')
    assert fragment.endswith('?src=xxx')


def test_drf_url():
    fragment = '{{ drf_url("addon-detail", pk="a3615") }}'
    rf = RequestFactory()

    request = rf.get('/hello/')
    rendered = render(fragment, context={'request': request})
    # As no /vX/ in the request, RESTFRAMEWORK['DEFAULT_VERSION'] is used.
    assert rendered == jinja_helpers.absolutify(
        reverse_ns('addon-detail', args=['a3615']))

    with pytest.raises(NoReverseMatch):
        # Without a request it can't resolve the name correctly.
        render(fragment, context={})


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

    s = render(
        u'{{ "https://foo.com/"|urlparams(param="obiwankénobi") }}', {})
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


@patch(
    'olympia.amo.templatetags.jinja_helpers.urlresolvers.'
    'get_outgoing_url')
def test_linkify_bounce_url_callback(mock_get_outgoing_url):
    mock_get_outgoing_url.return_value = 'bar'

    res = urlresolvers.linkify_bounce_url_callback({(None, 'href'): 'foo'})

    # Make sure get_outgoing_url was called.
    assert res == {(None, 'href'): 'bar'}
    mock_get_outgoing_url.assert_called_with('foo')


@patch(
    'olympia.amo.templatetags.jinja_helpers.urlresolvers.'
    'linkify_bounce_url_callback')
def test_linkify_with_outgoing_text_links(mock_linkify_bounce_url_callback):
    def side_effect(attrs, new=False):
        attrs[(None, 'href')] = 'bar'
        return attrs

    mock_linkify_bounce_url_callback.side_effect = side_effect

    res = urlresolvers.linkify_with_outgoing('a text http://example.com link')
    # Use PyQuery because the attributes could be rendered in any order.
    doc = PyQuery(res)
    assert doc('a[href="bar"][rel="nofollow"]')[0].text == 'http://example.com'


@patch(
    'olympia.amo.templatetags.jinja_helpers.urlresolvers.'
    'linkify_bounce_url_callback')
def test_linkify_with_outgoing_markup_links(mock_linkify_bounce_url_callback):
    def side_effect(attrs, new=False):
        attrs[(None, 'href')] = 'bar'
        return attrs

    mock_linkify_bounce_url_callback.side_effect = side_effect

    res = urlresolvers.linkify_with_outgoing(
        'a markup <a href="http://example.com">link</a> with text')
    # Use PyQuery because the attributes could be rendered in any order.
    doc = PyQuery(res)
    assert doc('a[href="bar"][rel="nofollow"]')[0].text == 'link'


def get_image_path(name):
    return os.path.join(
        settings.ROOT, 'src', 'olympia', 'amo', 'tests', 'images', name)


def get_uploaded_file(name):
    data = open(get_image_path(name), mode='rb').read()
    return SimpleUploadedFile(name, data,
                              content_type=mimetypes.guess_type(name)[0])


def get_addon_file(name):
    return os.path.join(ADDONS_TEST_FILES, name)


class TestAnimatedImages(TestCase):

    def test_animated_images(self):
        img = ImageCheck(open(get_image_path('animated.png'), mode='rb'))
        assert img.is_animated()
        img = ImageCheck(open(get_image_path('non-animated.png'), mode='rb'))
        assert not img.is_animated()

        img = ImageCheck(open(get_image_path('animated.gif'), mode='rb'))
        assert img.is_animated()
        img = ImageCheck(open(get_image_path('non-animated.gif'), mode='rb'))
        assert not img.is_animated()

    def test_junk(self):
        img = ImageCheck(open(__file__, 'rb'))
        assert not img.is_image()
        img = ImageCheck(open(get_image_path('non-animated.gif'), mode='rb'))
        assert img.is_image()


def test_jinja_trans_monkeypatch():
    # This tests the monkeypatch in manage.py that prevents localizers from
    # taking us down.
    render('{% trans come_on=1 %}% (come_on)s{% endtrans %}')
    render('{% trans come_on=1 %}%(come_on){% endtrans %}')
    render('{% trans come_on=1 %}%(come_on)z{% endtrans %}')


def test_absolutify():
    assert jinja_helpers.absolutify('/woo'), urljoin(
        settings.SITE_URL == '/woo')
    assert jinja_helpers.absolutify('https://addons.mozilla.org') == (
        'https://addons.mozilla.org')


def test_timesince():
    month_ago = datetime.now() - timedelta(days=30)
    assert jinja_helpers.timesince(month_ago) == u'1 month ago'
    assert jinja_helpers.timesince(None) == u''


def test_format_unicode():
    # This makes sure there's no UnicodeEncodeError when doing the string
    # interpolation.
    assert render(u'{{ "foo {0}"|format_html("baré") }}') == u'foo baré'


class TestStoragePath(TestCase):

    @override_settings(ADDONS_PATH=None, MEDIA_ROOT='/path/')
    def test_without_settings(self):
        del settings.ADDONS_PATH
        path = jinja_helpers.user_media_path('addons')
        assert path == '/path/addons'

    @override_settings(ADDONS_PATH='/another/path/')
    def test_with_settings(self):
        path = jinja_helpers.user_media_path('addons')
        assert path == '/another/path/'


class TestMediaUrl(TestCase):

    @override_settings(USERPICS_URL=None)
    def test_without_settings(self):
        del settings.USERPICS_URL
        settings.MEDIA_URL = '/mediapath/'
        url = jinja_helpers.user_media_url('userpics')
        assert url == '/mediapath/userpics/'
