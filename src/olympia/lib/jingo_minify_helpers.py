import os
import subprocess
import time

from django.conf import settings
from django.contrib.staticfiles.finders import find as find_static_path

import jinja2

try:
    from build import BUILD_ID_CSS, BUILD_ID_JS, BUILD_ID_IMG, BUNDLE_HASHES
except ImportError:
    BUILD_ID_CSS = BUILD_ID_JS = BUILD_ID_IMG = 'dev'
    BUNDLE_HASHES = {}


def is_external(url):
    """
    Determine if it is an external URL.
    """
    return url.startswith(('//', 'http://', 'https://'))


def _get_item_path(item):
    """
    Determine whether to return a relative path or a URL.
    """
    if is_external(item):
        return item
    return settings.STATIC_URL + item


def _get_mtime(item):
    """Get a last-changed timestamp for development."""
    if item.startswith(('//', 'http://', 'https://')):
        return int(time.time())
    return int(os.path.getmtime(find_static_path(item)))


def _build_html(items, wrapping):
    """
    Wrap `items` in wrapping.
    """
    return jinja2.Markup('\n'.join((wrapping % item for item in items)))


def ensure_path_exists(path):
    try:
        os.makedirs(os.path.dirname(path))
    except OSError as e:
        # If the directory already exists, that is fine. Otherwise re-raise.
        if e.errno != os.errno.EEXIST:
            raise

    return path


def get_js_urls(bundle, debug=None):
    """
    Fetch URLs for the JS files in the requested bundle.

    :param bundle:
        Name of the bundle to fetch.

    :param debug:
        If True, return URLs for individual files instead of the minified
        bundle.
    """
    if debug is None:
        debug = settings.DEBUG

    if debug:
        # Add timestamp to avoid caching.
        return [_get_item_path('%s?build=%s' % (item, _get_mtime(item))) for
                item in settings.MINIFY_BUNDLES['js'][bundle]]
    else:
        build_id = BUILD_ID_JS
        bundle_full = 'js:%s' % bundle
        if bundle_full in BUNDLE_HASHES:
            build_id = BUNDLE_HASHES[bundle_full]
        return (_get_item_path('js/%s-min.js?build=%s' % (bundle, build_id,)),)


def get_css_urls(bundle, debug=None):
    """
    Fetch URLs for the CSS files in the requested bundle.

    :param bundle:
        Name of the bundle to fetch.

    :param debug:
        If True, return URLs for individual files instead of the minified
        bundle.
    """
    if debug is None:
        debug = settings.DEBUG

    if debug:
        items = []
        for item in settings.MINIFY_BUNDLES['css'][bundle]:
            should_compile = (
                item.endswith('.less') and
                getattr(settings, 'LESS_PREPROCESS', False))

            if should_compile:
                compile_css(item)
                items.append('%s.css' % item)
            else:
                items.append(item)
        # Add timestamp to avoid caching.
        return [_get_item_path('%s?build=%s' % (item, _get_mtime(item))) for
                item in items]
    else:
        build_id = BUILD_ID_CSS
        bundle_full = 'css:%s' % bundle
        if bundle_full in BUNDLE_HASHES:
            build_id = BUNDLE_HASHES[bundle_full]
        return (_get_item_path('css/%s-min.css?build=%s' %
                               (bundle, build_id)),)


def compile_css(item):
    path_src = find_static_path(item)
    path_dst = os.path.join(
        settings.ROOT, 'static', '%s.css' % item)

    updated_src = os.path.getmtime(find_static_path(item))
    updated_dst = 0  # If the file doesn't exist, force a refresh.
    if os.path.exists(path_dst):
        updated_dst = os.path.getmtime(path_dst)

    # Is the uncompiled version newer?  Then recompile!
    if not updated_dst or updated_src > updated_dst:
        ensure_path_exists(os.path.dirname(path_dst))
        if item.endswith('.less'):
            with open(path_dst, 'w') as output:
                subprocess.Popen([settings.LESS_BIN, path_src], stdout=output)


def build_ids(request):
    """A context processor for injecting the css/js build ids."""
    return {'BUILD_ID_CSS': BUILD_ID_CSS, 'BUILD_ID_JS': BUILD_ID_JS,
            'BUILD_ID_IMG': BUILD_ID_IMG}
