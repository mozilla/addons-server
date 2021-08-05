import errno
import os
import subprocess

from django.conf import settings
from django.contrib.staticfiles.finders import find as find_static_path
from django.templatetags.static import static

import markupsafe


def _build_html(items, wrapping):
    """
    Wrap `items` in wrapping.
    """
    return markupsafe.Markup('\n'.join(wrapping % item for item in items))


def ensure_path_exists(path):
    try:
        os.makedirs(os.path.dirname(path))
    except OSError as e:
        # If the directory already exists, that is fine. Otherwise re-raise.
        if e.errno != errno.EEXIST:
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
        return [static(item) for item in settings.MINIFY_BUNDLES['js'][bundle]]
    else:
        return [static(f'js/{bundle}-min.js')]


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
            should_compile = item.endswith('.less') and getattr(
                settings, 'LESS_PREPROCESS', False
            )

            if should_compile:
                compile_css(item)
                items.append('%s.css' % item)
            else:
                items.append(item)
        return [static(item) for item in items]
    else:
        return [static(f'css/{bundle}-min.css')]


def compile_css(item):
    path_src = find_static_path(item)
    path_dst = os.path.join(settings.ROOT, 'static', '%s.css' % item)

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
