from django.conf import settings

from jinja2 import Markup
from jingo import register, env

import minify

try:
    from build import BUILD_ID_CSS, BUILD_ID_JS
except ImportError:
    BUILD_ID_CSS = BUILD_ID_JS = 'dev'

def _build_html(items, wrapping):
    """
    Wrap `items` in wrapping.
    """
    return Markup("\n".join((wrapping % (settings.MEDIA_URL + item)
                            for item in items)))


@register.function
def js(bundle, debug=settings.TEMPLATE_DEBUG):
    """
    If we are in debug mode, just output a single script tag for each js file.
    If we are not in debug mode, return a script that points at bundle-min.js.
    """
    if debug:
        items = minify.BUNDLES['js'][bundle]
    else:
        items = ("js/%s-min.js?build=%s" % (bundle, BUILD_ID_JS,),)

    return _build_html(items, """<script src="%s"></script>""")


@register.function
def css(bundle, media="screen,projection,tv", debug=settings.TEMPLATE_DEBUG):
    """
    If we are in debug mode, just output a single script tag for each css file.
    If we are not in debug mode, return a script that points at bundle-min.css.
    """
    if debug:
        items = minify.BUNDLES['css'][bundle]
    else:
        items = ("css/%s-min.css?build=%s" % (bundle, BUILD_ID_CSS,),)

    return _build_html(items,
            """<link rel="stylesheet" media="%s" href="%%s" />""" % media)
