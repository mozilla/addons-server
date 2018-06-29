import os

from django.conf import settings
from django.core.management import call_command
from django.test.utils import override_settings

import mock

from olympia.lib.jingo_minify_helpers import get_media_root, get_media_url
from olympia.amo.utils import from_string

try:
    from build import BUILD_ID_CSS, BUILD_ID_JS, BUILD_ID_IMG, BUNDLE_HASHES
except ImportError:
    BUILD_ID_CSS = BUILD_ID_JS = BUILD_ID_IMG = 'dev'
    BUNDLE_HASHES = {}


@mock.patch('jingo_minify.helpers.time.time')
@mock.patch('jingo_minify.helpers.os.path.getmtime')
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

    t = from_string("{{ js('common', debug=False) }}")
    s = t.render()

    eq_(s, '<script src="%sjs/common-min.js?build=%s"></script>' %
           (settings.STATIC_URL, BUILD_ID_JS))

    t = from_string("{{ js('common_url', debug=True) }}")
    s = t.render()

    eq_(s, '<script src="%s"></script>' %
           "http://example.com/test.js?build=1")

    t = from_string("{{ js('common_url', debug=False) }}")
    s = t.render()

    eq_(s, '<script src="%sjs/common_url-min.js?build=%s"></script>' %
           (settings.STATIC_URL, BUILD_ID_JS))

    t = from_string("{{ js('common_protocol_less_url', debug=True) }}")
    s = t.render()

    eq_(s, '<script src="%s"></script>' %
           "//example.com/test.js?build=1")

    t = from_string("{{ js('common_protocol_less_url', debug=False) }}")
    s = t.render()

    eq_(s, '<script src="%sjs/common_protocol_less_url-min.js?build=%s">'
           '</script>' % (settings.STATIC_URL, BUILD_ID_JS))

    t = from_string("{{ js('common_bundle', debug=True) }}")
    s = t.render()

    eq_(s, '<script src="js/test.js?build=1"></script>\n'
           '<script src="http://example.com/test.js?build=1"></script>\n'
           '<script src="//example.com/test.js?build=1"></script>\n'
           '<script src="https://example.com/test.js?build=1"></script>')

    t = from_string("{{ js('common_bundle', debug=False) }}")
    s = t.render()

    eq_(s, '<script src="%sjs/common_bundle-min.js?build=%s"></script>' %
           (settings.STATIC_URL, BUILD_ID_JS))


@mock.patch('jingo_minify.helpers.time.time')
@mock.patch('jingo_minify.helpers.os.path.getmtime')
def test_css_helper(getmtime, time):
    """
    Given the css() tag if we return the assets that make up that bundle
    as defined in settings.MINIFY_BUNDLES.

    If we're not in debug mode, we just return a minified url
    """
    getmtime.return_value = 1
    time.return_value = 1

    t = from_string("{{ css('common', debug=True) }}")
    s = t.render()

    expected = "\n".join([
        '<link rel="stylesheet" media="screen,projection,tv" '
        'href="%s?build=1" />' % (settings.STATIC_URL + j)
        for j in settings.MINIFY_BUNDLES['css']['common']
    ])

    eq_(s, expected)

    t = from_string("{{ css('common', debug=False) }}")
    s = t.render()

    eq_(s,
        '<link rel="stylesheet" media="screen,projection,tv" '
        'href="%scss/common-min.css?build=%s" />'
        % (settings.STATIC_URL, BUILD_ID_CSS))

    t = from_string("{{ css('common_url', debug=True) }}")
    s = t.render()

    eq_(s, '<link rel="stylesheet" media="screen,projection,tv" '
           'href="http://example.com/test.css?build=1" />')

    t = from_string("{{ css('common_url', debug=False) }}")
    s = t.render()

    eq_(s,
        '<link rel="stylesheet" media="screen,projection,tv" '
        'href="%scss/common_url-min.css?build=%s" />'
        % (settings.STATIC_URL, BUILD_ID_CSS))

    t = from_string("{{ css('common_protocol_less_url', debug=True) }}")
    s = t.render()

    eq_(s, '<link rel="stylesheet" media="screen,projection,tv" '
           'href="//example.com/test.css?build=1" />')

    t = from_string("{{ css('common_protocol_less_url', debug=False) }}")
    s = t.render()

    eq_(s,
        '<link rel="stylesheet" media="screen,projection,tv" '
        'href="%scss/common_protocol_less_url-min.css?build=%s" />'
        % (settings.STATIC_URL, BUILD_ID_CSS))

    t = from_string("{{ css('common_bundle', debug=True) }}")
    s = t.render()

    eq_(s, '<link rel="stylesheet" media="screen,projection,tv" '
           'href="css/test.css?build=1" />\n'
           '<link rel="stylesheet" media="screen,projection,tv" '
           'href="http://example.com/test.css?build=1" />\n'
           '<link rel="stylesheet" media="screen,projection,tv" '
           'href="//example.com/test.css?build=1" />\n'
           '<link rel="stylesheet" media="screen,projection,tv" '
           'href="https://example.com/test.css?build=1" />')

    t = from_string("{{ css('common_bundle', debug=False) }}")
    s = t.render()

    eq_(s, '<link rel="stylesheet" media="screen,projection,tv" '
           'href="%scss/common_bundle-min.css?build=%s" />' %
           (settings.STATIC_URL, BUILD_ID_CSS))


def test_inline_css_helper():
    t = from_string("{{ inline_css('common', debug=True) }}")
    s = t.render()

    eq_(s, '<style type="text/css" media="screen,projection,tv">'
           'body {\n    color: #999;\n}\n</style>')

    t = from_string("{{ inline_css('common', debug=False) }}")
    s = t.render()

    eq_(s, '<style type="text/css" media="screen,projection,tv">body'
           '{color:#999}</style>')


def test_inline_css_helper_multiple_files():
    t = from_string("{{ inline_css('common_multi', debug=True) }}")
    s = t.render()

    eq_(s, '<style type="text/css" media="screen,projection,tv">body {\n    '
           'color: #999;\n}\n</style>\n<style type="text/css" media="screen,'
           'projection,tv">body {\n    color: #999;\n}\n</style>')

    t = from_string("{{ inline_css('common_multi', debug=False) }}")
    s = t.render()

    eq_(s, '<style type="text/css" media="screen,projection,tv">body{color:'
           '#999}\nmain{font-size:1em}\n</style>')


def test_inline_css_helper_external_url():

    t = from_string("{{ inline_css('common_url', debug=True) }}")
    s = t.render()

    eq_(s, '<link rel="stylesheet" media="screen,projection,tv" '
           'href="http://example.com/test.css" />')

    t = from_string("{{ inline_css('common_url', debug=False) }}")
    s = t.render()

    eq_(s, '<style type="text/css" media="screen,projection,tv">'
        'body{color:#999}</style>')


@override_settings(STATIC_ROOT='static',
                   MEDIA_ROOT='media',
                   STATIC_URL='http://example.com/static/',
                   MEDIA_URL='http://example.com/media/')
def test_no_override():
    """No override uses STATIC versions."""
    eq_(get_media_root(), 'static')
    eq_(get_media_url(), 'http://example.com/static/')


@override_settings(JINGO_MINIFY_USE_STATIC=False,
                   STATIC_ROOT='static',
                   MEDIA_ROOT='media',
                   STATIC_URL='http://example.com/static/',
                   MEDIA_URL='http://example.com/media/')
def test_static_override():
    """Overriding to False uses MEDIA versions."""
    eq_(get_media_root(), 'media')
    eq_(get_media_url(), 'http://example.com/media/')


@override_settings(STATIC_ROOT='static',
                   MEDIA_ROOT='media',
                   STATIC_URL='http://example.com/static/',
                   MEDIA_URL='http://example.com/media/')
@mock.patch('jingo_minify.helpers.time.time')
@mock.patch('jingo_minify.helpers.os.path.getmtime')
def test_css(getmtime, time):
    getmtime.return_value = 1
    time.return_value = 1

    t = from_string("{{ css('common', debug=True) }}")
    s = t.render()

    expected = "\n".join(
        ['<link rel="stylesheet" media="screen,projection,tv" '
         'href="%s?build=1" />' % (settings.STATIC_URL + j)
         for j in settings.MINIFY_BUNDLES['css']['common']])

    eq_(s, expected)


@override_settings(STATIC_ROOT='static',
                   MEDIA_ROOT='media',
                   LESS_PREPROCESS=True,
                   LESS_BIN='lessc-bin',
                   SASS_BIN='sass-bin',
                   STYLUS_BIN='stylus-bin')
@mock.patch('jingo_minify.helpers.time.time')
@mock.patch('jingo_minify.helpers.os.path.getmtime')
@mock.patch('jingo_minify.helpers.subprocess')
@mock.patch('__builtin__.open', spec=True)
def test_compiled_css(open_mock, subprocess_mock, getmtime_mock, time_mock):
    jingo.get_env().from_string("{{ css('compiled', debug=True) }}").render()

    eq_(subprocess_mock.Popen.mock_calls,
        [mock.call(['lessc-bin', 'static/css/less.less'], stdout=ANY),
         mock.call(['sass-bin', 'static/css/sass.sass'], stdout=ANY),
         mock.call(['sass-bin', 'static/css/scss.scss'], stdout=ANY)])

    subprocess_mock.call.assert_called_with(
        'stylus-bin --include-css --include '
        'static/css < static/css/stylus.styl > static/css/stylus.styl.css',
        shell=True)


@override_settings(STATIC_ROOT='static',
                   MEDIA_ROOT='media',
                   STATIC_URL='http://example.com/static/',
                   MEDIA_URL='http://example.com/media/')
@mock.patch('jingo_minify.helpers.time.time')
@mock.patch('jingo_minify.helpers.os.path.getmtime')
def test_js(getmtime, time):
    getmtime.return_value = 1
    time.return_value = 1

    t = from_string("{{ js('common', debug=True) }}")
    s = t.render()

    expected = "\n".join(
        ['<script src="%s?build=1"></script>' % (settings.STATIC_URL + j)
         for j in settings.MINIFY_BUNDLES['js']['common']])

    eq_(s, expected)


@override_settings(
    MINIFY_BUNDLES={'css': {'common_multi': ['css/test.css', 'css/test2.css']}}
)
@mock.patch('jingo_minify.helpers.subprocess')
def test_compress_assets_command_with_git(subprocess_mock):
    build_id_file = os.path.realpath(os.path.join(settings.ROOT, 'build.py'))
    try:
        os.remove(build_id_file)
    except OSError:
        pass
    call_command('compress_assets')
    ok_(os.path.exists(build_id_file))
    with open(build_id_file) as f:
        contents_before = f.read()

    # Call command a second time. We should get the same build id, since it
    # depends on the git commit id.
    call_command('compress_assets')
    with open(build_id_file) as f:
        contents_after = f.read()

    eq_(contents_before, contents_after)


@override_settings(
    MINIFY_BUNDLES={'css': {'common_multi': ['css/test.css', 'css/test2.css']}}
)
@mock.patch('jingo_minify.helpers.subprocess')
def test_compress_assets_command_without_git(subprocess_mock):
    build_id_file = os.path.realpath(os.path.join(settings.ROOT, 'build.py'))
    try:
        os.remove(build_id_file)
    except OSError:
        pass
    call_command('compress_assets')
    ok_(os.path.exists(build_id_file))
    with open(build_id_file) as f:
        contents_before = f.read()

    # Call command a second time. We should get a different build id, since it
    # depends on a uuid.
    call_command('compress_assets', use_uuid=True)
    with open(build_id_file) as f:
        contents_after = f.read()

    ok_(contents_before != contents_after)
