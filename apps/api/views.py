"""
API views
"""
import json
import random
import datetime

from django.http import HttpResponse, HttpResponsePermanentRedirect
from django.utils import translation
from l10n import ugettext as _

import jingo

import amo
import api
from addons.models import Addon
from search.client import Client as SearchClient, SearchError

ERROR = 'error'
OUT_OF_DATE = _("The API version, {0:.1f}, you are using is not valid.  "
                "Please upgrade to the current version {1:.1f} API.")


def validate_api_version(version):
    """
    We want to be able to deprecate old versions of the API, therefore we check
    for a minimum API version before continuing.
    """
    if float(version) < api.MIN_VERSION:
        return False

    if float(version) > api.MAX_VERSION:
        return False

    return True


class APIView(object):
    """
    Base view class for all API views.
    """

    def __call__(self, request, api_version, *args, **kwargs):

        self.format = request.REQUEST.get('format', 'xml')
        self.mimetype = ('text/xml' if self.format == 'xml'
                         else 'application/json')
        self.request = request
        self.version = float(api_version)
        if not validate_api_version(api_version):
            msg = OUT_OF_DATE.format(self.version, api.CURRENT_VERSION)
            return self.render_msg(msg, ERROR, status=403,
                                   mimetype=self.mimetype)

        return self.process_request(*args, **kwargs)

    def render_msg(self, msg, error_level=None, *args, **kwargs):
        """
        Renders a simple message.
        """

        if self.format == 'xml':
            return jingo.render(self.request, 'api/message.xml',
                {'error_level': error_level, 'msg': msg}, *args, **kwargs)
        else:
            return HttpResponse(json.dumps({'msg': _(msg)}), *args, **kwargs)


class AddonDetailView(APIView):

    def process_request(self, addon_id):
        try:
            addon = Addon.objects.get(id=addon_id)
        except Addon.DoesNotExist:
            return self.render_msg('Add-on not found!', ERROR, status=404,
                mimetype=self.mimetype)

        return self.render_addon(addon)

    def render_addon(self, addon):
        if self.format == 'xml':
            return jingo.render(
                self.request, 'api/addon_detail.xml',
                {'addon': addon, 'amo': amo}, mimetype=self.mimetype)
        else:
            pass
            # serialize me?


class SearchView(APIView):

    def process_request(self, query, addon_type='ALL', limit=10, platform='ALL',
                        version=None):
        """
        This queries sphinx with `query` and serves the results in xml.
        """
        sc = SearchClient()

        opts = {'app': self.request.APP.id}

        if addon_type.upper() != 'ALL':
            opts['type'] = int(addon_type)

        if version:
            opts['version'] = version

        if platform.upper() != 'ALL':
            opts['platform'] = platform.lower()

        # By default we show public addons only for api_version < 1.5
        statuses = [amo.STATUS_PUBLIC]

        if (self.version >= 1.5
            and not self.request.REQUEST.get('hide_sandbox')):
            statuses.append(amo.STATUS_SANDBOX)

        opts['status'] = statuses

        try:
            results = sc.query(query, limit=int(limit), **opts)
        except SearchError:
            return self.render_msg('Could not connect to Sphinx search.',
                                   ERROR, status=503, mimetype=self.mimetype)

        if self.format == 'xml':
            return jingo.render(
                    self.request, 'api/search.xml',
                    {'results': results, 'total': sc.total_found},
                    mimetype=self.mimetype)


class ListView(APIView):

    def process_request(self, list_type='recommended', addon_type='ALL',
                        limit=3, platform='ALL', version=None):
        """
        This generates a list of addons that can be served to the
        AddonManager.

        We generate the lists by making empty queries to Sphinx, but with
        using parameters to influence the order.
        """
        if list_type == 'newest':
            # "New" is arbitrarily defined as 10 days old.
            qs = Addon.objects.filter(
                    created__gte=(datetime.date.today() -
                        datetime.timedelta(days=10)))
        else:
            qs = Addon.objects.featured(self.request.APP)

        if addon_type.lower() != 'all':
            addon_type = int(addon_type)
            if addon_type:
                qs = qs.filter(type=addon_type)

        if platform.lower() != 'all':
            qs = (qs.distinct() &
                  Addon.objects.compatible_with_platform(platform))

        if version is not None:
            qs = qs.distinct() & Addon.objects.compatible_with_app(
                    self.request.APP, version)

        locale_filter = Addon.objects.filter(
                description__locale=translation.get_language())
        addons = list(locale_filter.distinct() & qs.distinct())
        random.shuffle(addons)

        if len(addons) < limit:
            # We need to backfill.  Just do the same query, without the
            # language filter.
            moar_addons = list(qs.exclude(
                description__locale=translation.get_language()))
            random.shuffle(moar_addons)
            addons.extend(moar_addons)

        if self.format == 'xml':
            return jingo.render(self.request, 'api/list.xml',
                    {'addons': addons[:int(limit)]}, mimetype=self.mimetype)


# pylint: disable-msg=W0613
def redirect_view(request, url):
    """
    Redirect all requests that come here to an API call with a view parameter.
    """
    return HttpResponsePermanentRedirect('/api/%.1f/%s' %
        (api.CURRENT_VERSION, url))
