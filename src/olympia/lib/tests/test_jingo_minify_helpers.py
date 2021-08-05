import os

from django.conf import settings
from django.test.utils import override_settings

from unittest import mock

from olympia.amo.utils import from_string


TEST_MINIFY_BUNDLES = {
    'css': {
        'common': ['css/test.css'],
        'common_bundle': [
            'css/test.css',
            'css/test2.css',
        ],
        'compiled': ['css/plain.css', 'css/less.less'],
    },
    'js': {
        'common': ['js/test.js'],
        'common_bundle': [
            'js/test.js',
            'js/test2.js',
        ],
    },
}


@override_settings(MINIFY_BUNDLES=TEST_MINIFY_BUNDLES)
def test_js_helper():
    """
    Given the js() tag if we return the assets that make up that bundle
    as defined in settings.MINIFY_BUNDLES.

    If we're not in debug mode, we just return a minified url
    """
    template = from_string('{{ js("common", debug=True) }}')
    rendered = template.render()

    expected = '\n'.join(
        [
            '<script src="%s"></script>' % (settings.STATIC_URL + j)
            for j in settings.MINIFY_BUNDLES['js']['common']
        ]
    )

    assert rendered == expected

    template = from_string('{{ js("common", debug=False) }}')
    rendered = template.render()

    expected = f'<script src="{settings.STATIC_URL}js/common-min.js"></script>'
    assert rendered == expected

    template = from_string('{{ js("common_bundle", debug=True) }}')
    rendered = template.render()

    assert rendered == (
        f'<script src="{settings.STATIC_URL}js/test.js"></script>\n'
        f'<script src="{settings.STATIC_URL}js/test2.js"></script>'
    )

    template = from_string('{{ js("common_bundle", debug=False) }}')
    rendered = template.render()

    assert rendered == '<script src="{}js/common_bundle-min.js"></script>'.format(
        settings.STATIC_URL,
    )


@override_settings(MINIFY_BUNDLES=TEST_MINIFY_BUNDLES)
def test_css_helper():
    """
    Given the css() tag if we return the assets that make up that bundle
    as defined in settings.MINIFY_BUNDLES.

    If we're not in debug mode, we just return a minified url
    """
    template = from_string('{{ css("common", debug=True) }}')
    rendered = template.render()

    expected = '\n'.join(
        [
            '<link rel="stylesheet" media="all" '
            'href="%s" />' % (settings.STATIC_URL + j)
            for j in settings.MINIFY_BUNDLES['css']['common']
        ]
    )

    assert rendered == expected

    template = from_string('{{ css("common", debug=False) }}')
    rendered = template.render()

    expected = (
        '<link rel="stylesheet" media="all" '
        'href="%scss/common-min.css" />' % (settings.STATIC_URL,)
    )

    assert rendered == expected

    assert rendered == expected

    template = from_string('{{ css("common_bundle", debug=True) }}')
    rendered = template.render()

    assert rendered == (
        '<link rel="stylesheet" media="all" '
        f'href="{settings.STATIC_URL}css/test.css" />\n'
        '<link rel="stylesheet" media="all" '
        f'href="{settings.STATIC_URL}css/test2.css" />'
    )

    template = from_string('{{ css("common_bundle", debug=False) }}')
    rendered = template.render()

    assert (
        rendered == '<link rel="stylesheet" media="all" '
        'href="%scss/common_bundle-min.css" />' % (settings.STATIC_URL,)
    )


@override_settings(
    STATIC_URL='http://example.com/static/',
    MEDIA_URL='http://example.com/media/',
    MINIFY_BUNDLES=TEST_MINIFY_BUNDLES,
)
def test_css():
    template = from_string('{{ css("common", debug=True) }}')
    rendered = template.render()

    expected = '\n'.join(
        [
            '<link rel="stylesheet" media="all" '
            'href="%s" />' % (settings.STATIC_URL + j)
            for j in settings.MINIFY_BUNDLES['css']['common']
        ]
    )

    assert rendered == expected


@override_settings(MINIFY_BUNDLES={'css': {'compiled': ['css/impala/buttons.less']}})
@mock.patch('olympia.lib.jingo_minify_helpers.os.path.getmtime')
@mock.patch('olympia.lib.jingo_minify_helpers.subprocess')
@mock.patch('builtins.open', spec=True)
def test_compiled_css(open_mock, subprocess_mock, getmtime_mock):
    getmtime_mock.side_effect = [
        # The first call is for the source
        1531144805.1225898,
        # The second call is for the destination
        1530885814.6340182,
    ]

    from_string('{{ css("compiled", debug=True) }}")').render()

    source = os.path.realpath(
        os.path.join(settings.ROOT, 'static/css/impala/buttons.less')
    )

    assert subprocess_mock.Popen.mock_calls == [
        mock.call([settings.LESS_BIN, source], stdout=mock.ANY)
    ]


@override_settings(
    STATIC_URL='http://example.com/static/', MEDIA_URL='http://example.com/media/'
)
def test_js():
    template = from_string('{{ js("common", debug=True) }}')
    rendered = template.render()

    expected = '\n'.join(
        [
            '<script src="%s"></script>' % (settings.STATIC_URL + j)
            for j in settings.MINIFY_BUNDLES['js']['common']
        ]
    )

    assert rendered == expected
