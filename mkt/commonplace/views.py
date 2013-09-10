import importlib
import site

from django.conf import settings
from django.http import HttpResponseNotFound

import jingo

from mkt.api.resources import waffles


def commonplace(request, repo):
    if repo not in settings.COMMONPLACE_REPOS:
        raise HttpResponseNotFound

    site_settings = {
        'persona_unverified_issuer': settings.BROWSERID_DOMAIN
    }

    ctx = {
        'repo': repo,
        'site_settings': site_settings,
        'flags': waffles(request),
    }

    # This is where the `build_{repo}.py` files get written to after
    # compiling and minifying our assets.
    site.addsitedir('/var/tmp/')

    try:
        # Get the `BUILD_ID` from `build_{repo}.py` and use that to
        # cache-bust the assets for this repo's CSS/JS minified bundles.
        module = 'build_%s' % repo
        ctx['BUILD_ID'] = importlib.import_module(module).BUILD_ID
    except ImportError:
        # Fall back to `BUILD_ID_JS` which is written to `build.py` by
        # jingo-minify.
        pass

    return jingo.render(request, 'commonplace/index.html', ctx)
