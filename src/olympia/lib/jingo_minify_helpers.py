import os
import subprocess
import time

from django.conf import settings
from django.contrib.staticfiles.finders import find as static_finder

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
    return get_media_url() + item


def _get_mtime(item):
    """Get a last-changed timestamp for development."""
    if item.startswith(('//', 'http://', 'https://')):
        return int(time.time())
    return int(os.path.getmtime(get_path(item)))


def _build_html(items, wrapping):
    """
    Wrap `items` in wrapping.
    """
    return jinja2.Markup('\n'.join((wrapping % item for item in items)))


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


def _get_compiled_css_url(item):
    """
    Compresses a preprocess file and returns its relative compressed URL.

    :param item:
        Name of the less file to compress into css.
    """
    if item.endswith('.less') and getattr(settings, 'LESS_PREPROCESS', False):
        compile_css(item)
        return item + '.css'
    return item


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
            if ((item.endswith('.less') and
                    getattr(settings, 'LESS_PREPROCESS', False)) or
                    item.endswith(('.sass', '.scss', '.styl'))):
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


def ensure_path_exists(path):
    try:
        os.makedirs(path)
    except OSError as e:
        # If the directory already exists, that is fine. Otherwise re-raise.
        if e.errno != os.errno.EEXIST:
            raise


def compile_css(item):
    path_src = get_path(item)
    path_dst = get_path('%s.css' % item)

    updated_src = os.path.getmtime(get_path(item))
    updated_css = 0  # If the file doesn't exist, force a refresh.
    if os.path.exists(path_dst):
        updated_css = os.path.getmtime(path_dst)

    # Is the uncompiled version newer?  Then recompile!
    if not updated_css or updated_src > updated_css:
        ensure_path_exists(os.path.dirname(path_dst))
        if item.endswith('.less'):
            with open(path_dst, 'w') as output:
                subprocess.Popen([settings.LESS_BIN, path_src], stdout=output)


def build_ids(request):
    """A context processor for injecting the css/js build ids."""
    return {'BUILD_ID_CSS': BUILD_ID_CSS, 'BUILD_ID_JS': BUILD_ID_JS,
            'BUILD_ID_IMG': BUILD_ID_IMG}


def get_media_root():
    """Return STATIC_ROOT or MEDIA_ROOT depending on JINGO_MINIFY_USE_STATIC.
    This allows projects using Django 1.4 to continue using the old
    ways, but projects using Django 1.4 to use the new ways.
    """
    if getattr(settings, 'JINGO_MINIFY_ROOT', None):
        return settings.JINGO_MINIFY_ROOT
    if getattr(settings, 'JINGO_MINIFY_USE_STATIC', True):
        return settings.STATIC_ROOT
    return settings.MEDIA_ROOT


def get_media_url():
    """Return STATIC_URL or MEDIA_URL depending on JINGO_MINIFY_USE_STATIC.
    Allows projects using Django 1.4 to continue using the old ways
    but projects using Django 1.4 to use the new ways.
    """
    if getattr(settings, 'JINGO_MINIFY_USE_STATIC', True):
        return settings.STATIC_URL
    return settings.MEDIA_URL


def get_path(path):
    """Get a system path for a given file.
    This properly handles storing files in `project/app/static`, and any other
    location that Django's static files system supports.
    ``path`` should be relative to ``STATIC_ROOT``.
    """
    static = getattr(settings, 'JINGO_MINIFY_USE_STATIC', True)

    full_path = os.path.join(get_media_root(), path)

    if static:
        found_path = static_finder(path)
        # If the path is not found by Django's static finder (like we are
        # trying to get an output path), it returns None, so fall back.
        if found_path is not None:
            full_path = found_path

    return full_path
