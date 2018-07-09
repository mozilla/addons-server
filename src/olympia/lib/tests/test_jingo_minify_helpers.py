import os

from django.conf import settings
from django.test.utils import override_settings

import mock

from olympia.amo.utils import from_string

try:
    from build import BUILD_ID_CSS, BUILD_ID_JS, BUILD_ID_IMG, BUNDLE_HASHES
except ImportError:
    BUILD_ID_CSS = BUILD_ID_JS = BUILD_ID_IMG = 'dev'
    BUNDLE_HASHES = {}


TEST_MINIFY_BUNDLES = {
    'css': {
        'common': ['css/test.css'],
        'common_url': ['http://example.com/test.css'],
        'common_protocol_less_url': ['//example.com/test.css'],
        'common_bundle': ['css/test.css', 'http://example.com/test.css',
                          '//example.com/test.css',
                          'https://example.com/test.css'],
        'compiled': ['css/plain.css', 'css/less.less']
    },
    'js': {
        'common': ['js/test.js'],
        'common_url': ['http://example.com/test.js'],
        'common_protocol_less_url': ['//example.com/test.js'],
        'common_bundle': ['js/test.js', 'http://example.com/test.js',
                          '//example.com/test.js',
                          'https://example.com/test.js'],
    },
}


@override_settings(MINIFY_BUNDLES=TEST_MINIFY_BUNDLES)
@mock.patch('olympia.lib.jingo_minify_helpers.time.time')
@mock.patch('olympia.lib.jingo_minify_helpers.os.path.getmtime')
def test_js_helper(getmtime, time):
    """
    Given the js() tag if we return the assets that make up that bundle
    as defined in settings.MINIFY_BUNDLES.

    If we're not in debug mode, we just return a minified url
    """
    getmtime.return_value = 1
    time.return_value = 1

    template = from_string('{{ js("common", debug=True) }}')
    rendered = template.render()

    expected = '\n'.join([
        '<script src="%s?build=1"></script>' % (settings.STATIC_URL + j)
        for j in settings.MINIFY_BUNDLES['js']['common']])

    assert rendered == expected

    template = from_string('{{ js("common", debug=False) }}')
    rendered = template.render()

    expected = (
        '<script src="%sjs/common-min.js?build=%s"></script>' %
        (settings.STATIC_URL, BUILD_ID_JS))
    assert rendered == expected

    template = from_string('{{ js("common_url", debug=True) }}')
    rendered = template.render()

    expected = '<script src="http://example.com/test.js?build=1"></script>'
    assert rendered == expected

    template = from_string('{{ js("common_url", debug=False) }}')
    rendered = template.render()

    expected = (
        '<script src="%sjs/common_url-min.js?build=%s"></script>' %
        (settings.STATIC_URL, BUILD_ID_JS))
    assert rendered == expected

    template = from_string('{{ js("common_protocol_less_url", debug=True) }}')
    rendered = template.render()

    assert rendered == '<script src="//example.com/test.js?build=1"></script>'

    template = from_string('{{ js("common_protocol_less_url", debug=False) }}')
    rendered = template.render()

    expected = (
        '<script src="%sjs/common_protocol_less_url-min.js?build=%s"></script>'
        % (settings.STATIC_URL, BUILD_ID_JS))
    assert rendered == expected

    template = from_string('{{ js("common_bundle", debug=True) }}')
    rendered = template.render()

    assert (
        rendered == (
            '<script src="%sjs/test.js?build=1"></script>\n'
            '<script src="http://example.com/test.js?build=1"></script>\n'
            '<script src="//example.com/test.js?build=1"></script>\n'
            '<script src="https://example.com/test.js?build=1"></script>'
            % settings.STATIC_URL))

    template = from_string('{{ js("common_bundle", debug=False) }}')
    rendered = template.render()

    assert (
        rendered ==
        '<script src="%sjs/common_bundle-min.js?build=%s"></script>' %
           (settings.STATIC_URL, BUILD_ID_JS))


@override_settings(MINIFY_BUNDLES=TEST_MINIFY_BUNDLES)
@mock.patch('olympia.lib.jingo_minify_helpers.time.time')
@mock.patch('olympia.lib.jingo_minify_helpers.os.path.getmtime')
def test_css_helper(getmtime, time):
    """
    Given the css() tag if we return the assets that make up that bundle
    as defined in settings.MINIFY_BUNDLES.

    If we're not in debug mode, we just return a minified url
    """
    getmtime.return_value = 1
    time.return_value = 1

    template = from_string('{{ css("common", debug=True) }}')
    rendered = template.render()

    expected = "\n".join([
        '<link rel="stylesheet" media="all" '
        'href="%s?build=1" />' % (settings.STATIC_URL + j)
        for j in settings.MINIFY_BUNDLES['css']['common']
    ])

    assert rendered == expected

    template = from_string('{{ css("common", debug=False) }}')
    rendered = template.render()

    expected = (
        '<link rel="stylesheet" media="all" '
        'href="%scss/common-min.css?build=%s" />'
        % (settings.STATIC_URL, BUILD_ID_CSS))

    assert rendered == expected

    template = from_string('{{ css("common_url", debug=True) }}')
    rendered = template.render()

    expected = (
        '<link rel="stylesheet" media="all" '
        'href="http://example.com/test.css?build=1" />')
    assert rendered == expected

    template = from_string('{{ css("common_url", debug=False) }}')
    rendered = template.render()

    expected = (
        '<link rel="stylesheet" media="all" '
        'href="%scss/common_url-min.css?build=%s" />'
        % (settings.STATIC_URL, BUILD_ID_CSS))
    assert rendered == expected

    template = from_string('{{ css("common_protocol_less_url", debug=True) }}')
    rendered = template.render()

    assert (
        rendered == (
            '<link rel="stylesheet" media="all" '
            'href="//example.com/test.css?build=1" />'))

    template = from_string(
        '{{ css("common_protocol_less_url", debug=False) }}')
    rendered = template.render()

    expected = (
        '<link rel="stylesheet" media="all" '
        'href="%scss/common_protocol_less_url-min.css?build=%s" />'
        % (settings.STATIC_URL, BUILD_ID_CSS))

    assert rendered == expected

    template = from_string('{{ css("common_bundle", debug=True) }}')
    rendered = template.render()

    assert (
        rendered ==
        '<link rel="stylesheet" media="all" href="/static/css/test.css?build=1" />\n'  # noqa
        '<link rel="stylesheet" media="all" href="http://example.com/test.css?build=1" />\n'  # noqa
        '<link rel="stylesheet" media="all" href="//example.com/test.css?build=1" />\n'  # noqa
        '<link rel="stylesheet" media="all" href="https://example.com/test.css?build=1" />')  # noqa

    template = from_string('{{ css("common_bundle", debug=False) }}')
    rendered = template.render()

    assert (
        rendered ==
        '<link rel="stylesheet" media="all" '
        'href="%scss/common_bundle-min.css?build=%s" />' %
        (settings.STATIC_URL, BUILD_ID_CSS))


@override_settings(STATIC_URL='http://example.com/static/',
                   MEDIA_URL='http://example.com/media/',
                   MINIFY_BUNDLES=TEST_MINIFY_BUNDLES)
@mock.patch('olympia.lib.jingo_minify_helpers.time.time')
@mock.patch('olympia.lib.jingo_minify_helpers.os.path.getmtime')
def test_css(getmtime, time):
    getmtime.return_value = 1
    time.return_value = 1

    template = from_string('{{ css("common", debug=True) }}')
    rendered = template.render()

    expected = "\n".join(
        ['<link rel="stylesheet" media="all" '
         'href="%s?build=1" />' % (settings.STATIC_URL + j)
         for j in settings.MINIFY_BUNDLES['css']['common']])

    assert rendered == expected


@override_settings(MINIFY_BUNDLES={
    'css': {'compiled': ['css/impala/buttons.less']}})
@mock.patch('olympia.lib.jingo_minify_helpers.os.path.getmtime')
@mock.patch('olympia.lib.jingo_minify_helpers.subprocess')
@mock.patch('__builtin__.open', spec=True)
def test_compiled_css(open_mock, subprocess_mock, getmtime_mock):
    getmtime_mock.side_effect = [
        # The first call is for the source
        1531144805.1225898,
        # The second call is for the destination
        1530885814.6340182]

    from_string('{{ css("compiled", debug=True) }}")').render()

    source = os.path.realpath(os.path.join(
        settings.ROOT, 'static/css/impala/buttons.less'))

    assert subprocess_mock.Popen.mock_calls == [
        mock.call([settings.LESS_BIN, source], stdout=mock.ANY)]


@override_settings(STATIC_URL='http://example.com/static/',
                   MEDIA_URL='http://example.com/media/')
@mock.patch('olympia.lib.jingo_minify_helpers.time.time')
@mock.patch('olympia.lib.jingo_minify_helpers.os.path.getmtime')
def test_js(getmtime, time):
    getmtime.return_value = 1
    time.return_value = 1

    template = from_string('{{ js("common", debug=True) }}')
    rendered = template.render()

    expected = "\n".join(
        ['<script src="%s?build=1"></script>' % (settings.STATIC_URL + j)
         for j in settings.MINIFY_BUNDLES['js']['common']])

    assert rendered == expected
