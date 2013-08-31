import importlib

from django.conf import settings
from django.http import HttpResponseNotFound

import jingo


def commonplace(request, repo):
    if repo not in settings.COMMONPLACE_REPOS:
        raise HttpResponseNotFound

    site_settings = {
        'persona_unverified_issuer': settings.BROWSERID_DOMAIN
    }

    ctx = {
        'repo': repo,
        'site_settings': site_settings,
    }

    try:
        # Get the `BUILD_ID` from `build_{repo}.py` and use that to
        # cache-bust the assets for this repo's CSS/JS minified bundles.
        ctx['BUILD_ID'] = importlib.import_module('media.fireplace.build_%s' % repo).BUILD_ID
    except ImportError:
        pass

    return jingo.render(request, 'commonplace/index.html', ctx)
