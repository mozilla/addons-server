"""
API views
"""
import hashlib
import itertools
import json
import random
import urllib

from datetime import date, timedelta

from django.core.cache import cache
from django.db.transaction import non_atomic_requests
from django.http import HttpResponse, HttpResponsePermanentRedirect
from django.template import engines
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes
from django.utils.translation import get_language, ugettext, ugettext_lazy as _

import waffle

import olympia.core.logger

from olympia import amo, legacy_api
from olympia.addons.models import Addon, CompatOverride
from olympia.amo.decorators import allow_cross_site_request, json_view
from olympia.amo.models import manual_order
from olympia.amo.urlresolvers import get_url_prefix
from olympia.amo.utils import AMOJSONEncoder
from olympia.legacy_api.utils import addon_to_dict, find_compatible_version
from olympia.search.views import AddonSuggestionsAjax, PersonaSuggestionsAjax
from olympia.versions.compare import version_int
from olympia.lib.cache import cache_get_or_set


ERROR = 'error'
OUT_OF_DATE = _(
    u'The API version, {0:.1f}, you are using is not valid. '
    u'Please upgrade to the current version {1:.1f} API.')

xml_env = engines['jinja2'].env.overlay()
old_finalize = xml_env.finalize
xml_env.finalize = lambda x: amo.templatetags.jinja_helpers.strip_controls(
    old_finalize(x))


# Hard limit of 30.  The buffer is to try for locale-specific add-ons.
MAX_LIMIT, BUFFER = 30, 10

# "New" is arbitrarily defined as 10 days old.
NEW_DAYS = 10

log = olympia.core.logger.getLogger('z.api')


def partition(seq, key):
    """Group a sequence based into buckets by key(x)."""
    groups = itertools.groupby(sorted(seq, key=key), key=key)
    return ((k, list(v)) for k, v in groups)


def render_xml_to_string(request, template, context=None):
    if context is None:
        context = {}

    for processor in engines['jinja2'].context_processors:
        context.update(processor(request))

    template = xml_env.get_template(template)
    return template.render(context)


@non_atomic_requests
def render_xml(request, template, context=None, **kwargs):
    """Safely renders xml, stripping out nasty control characters."""
    if context is None:
        context = {}
    rendered = render_xml_to_string(request, template, context)

    if 'content_type' not in kwargs:
        kwargs['content_type'] = 'text/xml'

    return HttpResponse(rendered, **kwargs)


@non_atomic_requests
def handler403(request):
    context = {'error_level': ERROR, 'msg': 'Not allowed'}
    return render_xml(request, 'legacy_api/message.xml', context, status=403)


@non_atomic_requests
def handler404(request):
    context = {'error_level': ERROR, 'msg': 'Not Found'}
    return render_xml(request, 'legacy_api/message.xml', context, status=404)


@non_atomic_requests
def handler500(request):
    context = {'error_level': ERROR, 'msg': 'Server Error'}
    return render_xml(request, 'legacy_api/message.xml', context, status=500)


def validate_api_version(version):
    """
    We want to be able to deprecate old versions of the API, therefore we check
    for a minimum API version before continuing.
    """
    if float(version) < legacy_api.MIN_VERSION:
        return False

    if float(version) > legacy_api.MAX_VERSION:
        return False

    return True


def addon_filter(addons, addon_type, limit, app, platform, version,
                 compat_mode='strict', shuffle=True):
    """
    Filter addons by type, application, app version, and platform.

    Add-ons that support the current locale will be sorted to front of list.
    Shuffling will be applied to the add-ons supporting the locale and the
    others separately.

    Doing this in the database takes too long, so we do it in code and wrap
    it in generous caching.
    """
    APP = app

    if addon_type.upper() != 'ALL':
        try:
            addon_type = int(addon_type)
            if addon_type:
                addons = [a for a in addons if a.type == addon_type]
        except ValueError:
            # `addon_type` is ALL or a type id.  Otherwise we ignore it.
            pass

    # Take out personas since they don't have versions.
    groups = dict(partition(addons,
                            lambda x: x.type == amo.ADDON_PERSONA))
    personas, addons = groups.get(True, []), groups.get(False, [])

    platform = platform.lower()
    if platform != 'all' and platform in amo.PLATFORM_DICT:
        def f(ps):
            return pid in ps or amo.PLATFORM_ALL in ps

        pid = amo.PLATFORM_DICT[platform]
        addons = [a for a in addons
                  if f(a.current_version.supported_platforms)]

    if version is not None:
        vint = version_int(version)

        def f_strict(app):
            return app.min.version_int <= vint <= app.max.version_int

        def f_ignore(app):
            return app.min.version_int <= vint

        xs = [(a, a.compatible_apps) for a in addons]

        # Iterate over addons, checking compatibility depending on compat_mode.
        addons = []
        for addon, apps in xs:
            app = apps.get(APP)
            if compat_mode == 'strict':
                if app and f_strict(app):
                    addons.append(addon)
            elif compat_mode == 'ignore':
                if app and f_ignore(app):
                    addons.append(addon)
            elif compat_mode == 'normal':
                # This does a db hit but it's cached. This handles the cases
                # for strict opt-in, binary components, and compat overrides.
                v = find_compatible_version(addon, APP.id, version, platform,
                                            compat_mode)
                if v:  # There's a compatible version.
                    addons.append(addon)

    # Put personas back in.
    addons.extend(personas)

    # We prefer add-ons that support the current locale.
    lang = get_language()

    def partitioner(x):
        return x.description is not None and (x.description.locale == lang)

    groups = dict(partition(addons, partitioner))
    good, others = groups.get(True, []), groups.get(False, [])

    if shuffle:
        random.shuffle(good)
        random.shuffle(others)

    # If limit=0, we return all addons with `good` coming before `others`.
    # Otherwise pad `good` if less than the limit and return the limit.
    if limit > 0:
        if len(good) < limit:
            good.extend(others[:limit - len(good)])
        return good[:limit]
    else:
        good.extend(others)
        return good


class APIView(object):
    """
    Base view class for all API views.
    """

    @method_decorator(non_atomic_requests)
    def __call__(self, request, api_version, *args, **kwargs):

        self.version = float(api_version)
        self.format = request.GET.get('format', 'xml')
        self.content_type = ('text/xml' if self.format == 'xml'
                             else 'application/json')
        self.request = request
        if not validate_api_version(api_version):
            msg = OUT_OF_DATE.format(self.version, legacy_api.CURRENT_VERSION)
            return self.render_msg(msg, ERROR, status=403,
                                   content_type=self.content_type)

        return self.process_request(*args, **kwargs)

    def render_msg(self, msg, error_level=None, *args, **kwargs):
        """
        Renders a simple message.
        """

        if self.format == 'xml':
            return render_xml(
                self.request, 'legacy_api/message.xml',
                {'error_level': error_level, 'msg': msg}, *args, **kwargs)
        else:
            return HttpResponse(json.dumps({'msg': _(msg)}), *args, **kwargs)

    def render(self, template, context):
        context['api_version'] = self.version
        context['api'] = legacy_api

        if self.format == 'xml':
            return render_xml(self.request, template, context,
                              content_type=self.content_type)
        else:
            return HttpResponse(self.render_json(context),
                                content_type=self.content_type)

    def render_json(self, context):
        return json.dumps({'msg': ugettext('Not implemented yet.')})


class AddonDetailView(APIView):

    @allow_cross_site_request
    def process_request(self, addon_id):
        try:
            # Nominated or public add-ons should be viewable using the legacy
            # API detail endpoint.
            addon = Addon.objects.valid().id_or_slug(addon_id).get()
        except Addon.DoesNotExist:
            # Add-on is either inexistent or not public/nominated.
            return self.render_msg(
                'Add-on not found!', ERROR, status=404,
                content_type=self.content_type
            )
        return self.render_addon(addon)

    def render_addon(self, addon):
        return self.render('legacy_api/addon_detail.xml', {'addon': addon})

    def render_json(self, context):
        return json.dumps(addon_to_dict(context['addon']), cls=AMOJSONEncoder)


@non_atomic_requests
def guid_search(request, api_version, guids):
    lang = request.LANG
    app_id = request.APP.id

    def guid_search_cache_key(guid):
        key = 'guid_search:%s:%s:%s:%s' % (api_version, lang, app_id, guid)
        return hashlib.sha256(force_bytes(key)).hexdigest()

    guids = [guid.strip() for guid in guids.split(',')] if guids else []

    addons_xml = cache.get_many(
        [guid_search_cache_key(guid) for guid in guids])
    dirty_keys = set()

    for guid in guids:
        key = guid_search_cache_key(guid)
        if key not in addons_xml:
            dirty_keys.add(key)
            try:
                # Only search through public (and not disabled) add-ons.
                addon = Addon.objects.public().get(guid=guid)
            except Addon.DoesNotExist:
                addons_xml[key] = ''

            else:
                addon_xml = render_xml_to_string(
                    request, 'legacy_api/includes/addon.xml', {
                        'addon': addon,
                        'api_version': api_version,
                        'api': legacy_api
                    })
                addons_xml[key] = addon_xml

    if dirty_keys:
        cache.set_many(dict((k, v) for k, v in addons_xml.iteritems()
                            if k in dirty_keys))

    compat = (CompatOverride.objects.filter(guid__in=guids)
              .transform(CompatOverride.transformer))

    addons_xml = [v for v in addons_xml.values() if v]
    return render_xml(request, 'legacy_api/search.xml', {
        'addons_xml': addons_xml,
        'total': len(addons_xml),
        'compat': compat,
        'api_version': api_version, 'api': legacy_api
    })


class SearchView(APIView):

    def process_request(self, query, addon_type='ALL', limit=10,
                        platform='ALL', version=None, compat_mode='strict'):
        """
        Query the search backend and serve up the XML.
        """
        limit = min(MAX_LIMIT, int(limit))
        app_id = self.request.APP.id

        # We currently filter for status=PUBLIC for all versions. If
        # that changes, the contract for API version 1.5 requires
        # that we continue filtering for it there.
        filters = {
            'app': app_id,
            'status': amo.STATUS_PUBLIC,
            'is_experimental': False,
            'is_disabled': False,
            'current_version__exists': True,
        }

        params = {'version': version, 'platform': None}

        # Specific case for Personas (bug 990768): if we search providing the
        # Persona addon type (9), don't filter on the platform as Personas
        # don't have compatible platforms to filter on.
        if addon_type != '9':
            params['platform'] = platform

        # Type filters.
        if addon_type:
            try:
                atype = int(addon_type)
                if atype in amo.ADDON_SEARCH_TYPES:
                    filters['type'] = atype
            except ValueError:
                atype = amo.ADDON_SEARCH_SLUGS.get(addon_type.lower())
                if atype:
                    filters['type'] = atype

        if 'type' not in filters:
            # Filter by ALL types, which is really all types except for apps.
            filters['type__in'] = list(amo.ADDON_SEARCH_TYPES)

        if self.version < 1.5:
            # Fix doubly encoded query strings.
            try:
                query = urllib.unquote(query.encode('ascii'))
            except UnicodeEncodeError:
                # This fails if the string is already UTF-8.
                pass

        results = []
        qs = (
            Addon.search()
            .filter(**filters)
            .filter_query_string(query)
            [:limit])

        for addon in qs:
            compat_version = find_compatible_version(
                addon, app_id, params['version'], params['platform'],
                compat_mode)
            # Specific case for Personas (bug 990768): if we search
            # providing the Persona addon type (9), then don't look for a
            # compatible version.
            if compat_version or addon_type == '9':
                addon.compat_version = compat_version
                results.append(addon)
                if len(results) == limit:
                    break

        return self.render('legacy_api/search.xml', {
            'results': results,
            'total': len(results),
            # For caching
            'version': version,
            'compat_mode': compat_mode,
        })


@json_view
@non_atomic_requests
def search_suggestions(request):
    if waffle.sample_is_active('autosuggest-throttle'):
        return HttpResponse(status=503)
    cat = request.GET.get('cat', 'all')
    suggesterClass = {
        'all': AddonSuggestionsAjax,
        'themes': PersonaSuggestionsAjax,
    }.get(cat, AddonSuggestionsAjax)
    items = suggesterClass(request, ratings=True).items
    for s in items:
        s['rating'] = float(s['rating'])
    return {'suggestions': items}


class ListView(APIView):

    def process_request(self, list_type='recommended', addon_type='ALL',
                        limit=10, platform='ALL', version=None,
                        compat_mode='strict'):
        """
        Find a list of new or featured add-ons.  Filtering is done in Python
        for cache-friendliness and to avoid heavy queries.
        """
        limit = min(MAX_LIMIT, int(limit))
        APP, platform = self.request.APP, platform.lower()
        qs = Addon.objects.listed(APP)
        shuffle = True

        if list_type in ('by_adu', 'featured'):
            qs = qs.exclude(type=amo.ADDON_PERSONA)

        if list_type == 'newest':
            new = date.today() - timedelta(days=NEW_DAYS)
            addons = (qs.filter(created__gte=new)
                      .order_by('-created'))[:limit + BUFFER]
        elif list_type == 'by_adu':
            addons = qs.order_by('-average_daily_users')[:limit + BUFFER]
            shuffle = False  # By_adu is an ordered list.
        elif list_type == 'hotness':
            # Filter to type=1 so we hit visible_idx. Only extensions have a
            # hotness index right now so this is not incorrect.
            addons = (qs.filter(type=amo.ADDON_EXTENSION)
                      .order_by('-hotness'))[:limit + BUFFER]
            shuffle = False
        else:
            ids = Addon.featured_random(APP, self.request.LANG)
            addons = manual_order(qs, ids[:limit + BUFFER], 'addons.id')
            shuffle = False

        args = (addon_type, limit, APP.id, platform, version, compat_mode,
                shuffle)

        cache_key = 'olympia.views.legacy_api.views:ListView:{}'.format(
            hashlib.sha256(':'.join(map(force_bytes, args))).hexdigest())

        addons = cache_get_or_set(cache_key, lambda: list(addons.all()))

        return self.render('legacy_api/list.xml',
                           {'addons': addon_filter(addons, *args)})

    def render_json(self, context):
        return json.dumps([addon_to_dict(a) for a in context['addons']],
                          cls=AMOJSONEncoder)


class LanguageView(APIView):

    def process_request(self):
        addons = (Addon.objects.public()
                               .filter(type=amo.ADDON_LPAPP,
                                       appsupport__app=self.request.APP.id)
                               .order_by('pk'))
        return self.render('legacy_api/list.xml', {'addons': addons,
                                                   'show_localepicker': True})


# pylint: disable-msg=W0613
@non_atomic_requests
def redirect_view(request, url):
    """
    Redirect all requests that come here to an API call with a view parameter.
    """
    dest = '/api/%.1f/%s' % (legacy_api.CURRENT_VERSION,
                             urllib.quote(url.encode('utf-8')))
    dest = get_url_prefix().fix(dest)

    return HttpResponsePermanentRedirect(dest)
