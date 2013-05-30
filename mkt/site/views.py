import hashlib
import json
import logging
import os
import subprocess

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import (HttpResponse, HttpResponseNotFound,
                         HttpResponseServerError)
from django.shortcuts import get_object_or_404, redirect
from django.template import RequestContext
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_exempt, requires_csrf_token
from django.views.decorators.http import etag

import jingo
import jingo_minify
from django_statsd.clients import statsd
from django_statsd.views import record as django_statsd_record
from jingo import render_to_string

from amo.context_processors import get_collect_timings
from amo.decorators import post_required
from amo.helpers import media
from amo.urlresolvers import reverse
from amo.utils import urlparams

from mkt.carriers import get_carrier
from mkt.detail.views import manifest as mini_manifest
from mkt.webapps.models import Webapp


log = logging.getLogger('z.mkt.site')


# This can be called when CsrfViewMiddleware.process_view has not run,
# therefore needs @requires_csrf_token in case the template needs
# {% csrf_token %}.
@requires_csrf_token
def handler403(request):
    # NOTE: The mkt.api uses Tastypie which has its own mechanism for
    # triggering 403s. If we ever end up calling PermissionDenied there, we'll
    # need something here similar to the 404s and 500s.
    #
    # TODO: Bug 793241 for different 403 templates at different URL paths.
    return jingo.render(request, 'site/403.html', status=403)


def handler404(request):
    if request.path_info.startswith('/api/'):
        # Pass over to API handler404 view if API was targeted.
        return HttpResponseNotFound()
    else:
        return jingo.render(request, 'site/404.html', status=404)


def handler500(request):
    if request.path_info.startswith('/api/'):
        # Pass over to API handler500 view if API was targeted.
        return HttpResponseServerError()
    else:
        return jingo.render(request, 'site/500.html', status=500)


def csrf_failure(request, reason=''):
    return jingo.render(request, 'site/403.html',
                        {'because_csrf': 'CSRF' in reason}, status=403)


def manifest(request):
    ctx = RequestContext(request)
    data = {
        'name': getattr(settings, 'WEBAPP_MANIFEST_NAME',
                        'Firefox Marketplace'),
        'description': 'The Firefox Marketplace',
        'developer': {
            'name': 'Mozilla',
            'url': 'http://mozilla.org',
        },
        'icons': {
            # Using the default addon image until we get a marketplace logo.
            '128': media(ctx, 'img/mkt/logos/128.png'),
            '64': media(ctx, 'img/mkt/logos/64.png'),
            '32': media(ctx, 'img/mkt/logos/32.png'),
        },
        'activities': {
            'marketplace-app': {'href': '/'},
            'marketplace-app-rating': {'href': '/'},
            'marketplace-category': {'href': '/'},
            'marketplace-search': {'href': '/'},
        },
        'orientation': ['portrait-primary']
    }
    if settings.USE_APPCACHE:
        data['appcache_path'] = reverse('django_appcache.manifest')
    if get_carrier():
        data['launch_path'] = urlparams('/', carrier=get_carrier())

    manifest_content = json.dumps(data)
    manifest_etag = hashlib.md5(manifest_content).hexdigest()

    @etag(lambda r: manifest_etag)
    def _inner_view(request):
        response = HttpResponse(manifest_content,
                                mimetype='application/x-web-app-manifest+json')
        return response

    return _inner_view(request)


def package_minifest(request):
    """Serves the mini manifest ("minifest") for the packaged `.zip`."""
    if not settings.MARKETPLACE_GUID:
        return HttpResponseNotFound()
    return mini_manifest(request, settings.MARKETPLACE_GUID)


def robots(request):
    """Generate a `robots.txt`."""
    template = jingo.render(request, 'site/robots.txt')
    return HttpResponse(template, mimetype='text/plain')


@csrf_exempt
@post_required
def record(request):
    # The rate limiting is done up on the client, but if things go wrong
    # we can just turn the percentage down to zero.
    if get_collect_timings():
        return django_statsd_record(request)
    raise PermissionDenied


# Cache this for an hour so that newly deployed changes are available within
# an hour. This will be served from the CDN which mimics these headers.
@cache_page(60 * 60)
def mozmarket_js(request):
    vendor_js = []
    for lib, path in (('receiptverifier',
                       'receiptverifier/receiptverifier.js'),):
        if lib in settings.MOZMARKET_VENDOR_EXCLUDE:
            continue
        with open(os.path.join(settings.ROOT,
                               'vendor', 'js', path), 'r') as fp:
            vendor_js.append((lib, fp.read()))
    js = render_to_string(request, 'site/mozmarket.js',
                          {'vendor_js': vendor_js})
    if settings.MINIFY_MOZMARKET:
        js = minify_js(js)
    return HttpResponse(js, content_type='text/javascript')


@statsd.timer('mkt.mozmarket.minify')
def minify_js(js):
    if settings.UGLIFY_BIN:
        log.info('minifying JS with uglify')
        return _minify_js_with_uglify(js)
    else:
        # The YUI fallback here is important
        # because YUI compressor is bundled with jingo
        # minify and therefore doesn't require any deps.
        log.info('minifying JS with YUI')
        return _minify_js_with_yui(js)


def _minify_js_with_uglify(js):
    sp = _open_pipe([settings.UGLIFY_BIN])
    js, err = sp.communicate(js)
    if sp.returncode != 0:
        raise ValueError('Compressing JS with uglify failed; error: %s'
                         % err.strip())
    return js


def _minify_js_with_yui(js):
    jar = os.path.join(os.path.dirname(jingo_minify.__file__), 'bin',
                       'yuicompressor-2.4.7.jar')
    if not os.path.exists(jar):
        raise ValueError('Could not find YUI compressor; tried %r' % jar)
    sp = _open_pipe([settings.JAVA_BIN, '-jar', jar, '--type', 'js',
                     '--charset', 'utf8'])
    js, err = sp.communicate(js)
    if sp.returncode != 0:
        raise ValueError('Compressing JS with YUI failed; error: %s'
                         % err.strip())
    return js


def _open_pipe(cmd):
    return subprocess.Popen(cmd,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)


def fireplace(request):
    return jingo.render(request, 'site/fireplace.html')
