from django.conf import settings

import jingo
from nose.tools import eq_


try:
    from build import BUILD_ID_CSS, BUILD_ID_JS
except:
    BUILD_ID_CSS = BUILD_ID_JS = 'dev'

def setup():
    jingo.load_helpers()

def test_js_helper():
    """
    Given the js() tag if we return the assets that make up that bundle
    as defined in settings.MINIFY_BUNDLES.

    If we're not in debug mode, we just return a minified url
    """

    env = jingo.env

    t = env.from_string("{{ js('common', debug=True) }}")
    s = t.render()

    expected ="\n".join(["""<script src="%s"></script>""" % (settings.MEDIA_URL + j)
                        for j in settings.MINIFY_BUNDLES['js']['common']])

    eq_(s, expected)

    t = env.from_string("{{ js('common', debug=False) }}")
    s = t.render()

    eq_(s, """<script src="%s"></script>""" %
           (settings.MEDIA_URL + "js/common-min.js?build=%s" % BUILD_ID_JS))


def test_css_helper():
    """
    Given the css() tag if we return the assets that make up that bundle
    as defined in settings.MINIFY_BUNDLES.

    If we're not in debug mode, we just return a minified url
    """
    env = jingo.env

    t = env.from_string("{{ css('common', debug=True) }}")
    s = t.render()

    expected ="\n".join(
        ["""<link rel="stylesheet" media="screen,projection,tv" href="%s" />"""
         % (settings.MEDIA_URL + j) for j in
         settings.MINIFY_BUNDLES['css']['common']])

    eq_(s, expected)

    t = env.from_string("{{ css('common', debug=False) }}")
    s = t.render()

    eq_(s,
        """<link rel="stylesheet" media="screen,projection,tv" href="%s" />"""
        % (settings.MEDIA_URL + "css/common-min.css?build=%s" % BUILD_ID_CSS))
