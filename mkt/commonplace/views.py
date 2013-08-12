from django.conf import settings
from django.http import HttpResponseNotFound

import jingo


def commonplace(request, repo):
    if repo not in settings.COMMONPLACE_REPOS:
        raise HttpResponseNotFound

    site_settings = {
        'persona_unverified_issuer': settings.BROWSERID_DOMAIN
    }

    return jingo.render(request, 'commonplace/index.html', {
        'repo': repo,
        'site_settings': site_settings,
    })
