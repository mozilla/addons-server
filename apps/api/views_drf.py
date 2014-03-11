"""
This view is a port of the views.py file (using Piston) to DRF.
It is a work in progress that is supposed to replace the views.py completely.
"""
import urllib
from datetime import date, timedelta

from django.conf import settings
from django.utils import encoding

from caching.base import cached_with
from rest_framework.response import Response
from rest_framework.views import APIView

import amo
from addons.models import Addon
from amo.decorators import allow_cross_site_request
from amo.models import manual_order
import api
from search.views import name_query

from .renderers import JSONRenderer, XMLTemplateRenderer
from .utils import addon_to_dict, extract_filters
from .views import (BUFFER, ERROR, MAX_LIMIT, NEW_DAYS, OUT_OF_DATE,
                    addon_filter)


class DRFView(APIView):

    def initial(self, request, *args, **kwargs):
        """
        Storing the `format` and the `api_version` for future use.
        """
        super(DRFView, self).initial(request, *args, **kwargs)
        # `settings.URL_FORMAT_OVERRIDE` referers to
        # https://github.com/tomchristie/django-rest-framework/blob/master/rest_framework/negotiation.py#L39
        self.format = kwargs.get('format', None) or request.QUERY_PARAMS.get(
            getattr(settings, 'URL_FORMAT_OVERRIDE'), 'xml')
        self.api_version = float(kwargs['api_version'])

    def get_renderer_context(self):
        context = super(DRFView, self).get_renderer_context()
        context.update({
            'amo': amo,
            'api_version': self.api_version,
        })
        return context

    def create_response(self, results):
        """
        Creates a different Response object given the format type.
        """
        if self.format == 'xml':
            return Response(self.serialize_to_xml(results),
                            template_name=self.template_name)
        else:
            return Response(self.serialize_to_json(results))


class AddonDetailView(DRFView):

    renderer_classes = (XMLTemplateRenderer, JSONRenderer)
    template_name = 'api/addon_detail.xml'
    error_template_name = 'api/message.xml'

    @allow_cross_site_request
    def get(self, request, addon_id, api_version, format=None):
        # Check valid version.
        if (self.api_version < api.MIN_VERSION
            or self.api_version > api.MAX_VERSION):
            msg = OUT_OF_DATE.format(self.api_version, api.CURRENT_VERSION)
            return Response({'msg': msg},
                            template_name=self.error_template_name, status=403)
        # Retrieve addon.
        try:
            addon = (Addon.objects.id_or_slug(addon_id)
                                  .exclude(type=amo.ADDON_WEBAPP).get())
        except Addon.DoesNotExist:
            return Response({'msg': 'Add-on not found!'},
                            template_name=self.error_template_name, status=404)
        if addon.is_disabled:
            return Response({'error_level': ERROR, 'msg': 'Add-on disabled.'},
                            template_name=self.error_template_name, status=404)

        return self.create_response(addon)

    def serialize_to_xml(self, results):
        return {'addon': results}

    def serialize_to_json(self, results):
        return addon_to_dict(results)


class LanguageView(DRFView):

    renderer_classes = (XMLTemplateRenderer,)
    template_name = 'api/list.xml'

    def get_renderer_context(self):
        context = super(LanguageView, self).get_renderer_context()
        context.update({
            'show_localepicker': True,
        })
        return context

    def get(self, request, api_version):
        addons = Addon.objects.filter(status=amo.STATUS_PUBLIC,
                                      type=amo.ADDON_LPAPP,
                                      appsupport__app=self.request.APP.id,
                                      disabled_by_user=False).order_by('pk')
        return Response({
            'addons': addons,
        }, template_name=self.template_name)


class SearchView(DRFView):

    renderer_classes = (XMLTemplateRenderer,)
    template_name = 'api/search.xml'

    def get_renderer_context(self):
        context = super(SearchView, self).get_renderer_context()
        context.update({
            # For caching
            'version': self.version,
            'compat_mode': self.compat_mode,
        })
        return context

    def get(self, request, api_version, query, addon_type='ALL', limit=10,
            platform='ALL', version=None, compat_mode='strict'):
        """
        Query the search backend and serve up the XML.
        """
        self.compat_mode = compat_mode
        self.version = version
        limit = min(MAX_LIMIT, int(limit))
        app_id = self.request.APP.id

        filters = {
            'app': app_id,
            'status': amo.STATUS_PUBLIC,
            'is_disabled': False,
            'has_version': True,
        }

        # Opts may get overridden by query string filters.
        opts = {
            'addon_type': addon_type,
            'platform': platform,
            'version': version,
        }

        if self.api_version < 1.5:
            # By default we show public addons only for api_version < 1.5.
            filters['status__in'] = [amo.STATUS_PUBLIC]

            # Fix doubly encoded query strings.
            try:
                query = urllib.unquote(query.encode('ascii'))
            except UnicodeEncodeError:
                # This fails if the string is already UTF-8.
                pass

        query, qs_filters = extract_filters(query, filters['app'], opts)

        qs = Addon.search().query(or_=name_query(query))
        filters.update(qs_filters)
        if 'type' not in filters:
            # Filter by ALL types, which is really all types except for apps.
            filters['type__in'] = list(amo.ADDON_SEARCH_TYPES)
        qs = qs.filter(**filters)

        if qs_filters.get('platform__in', []):
            # More than one platform, pluck it out.
            platforms = qs_filters.get('platform__in')[:]
            platforms.remove(1)  # ALL is already queried in compat SQL.
            if platforms:
                platform = amo.PLATFORMS[platforms[0]].api_name

        total = qs.count()

        results = []
        for addon in qs:
            compat_version = addon.compatible_version(app_id, version,
                                                      platform, compat_mode)
            if compat_version:
                addon.compat_version = compat_version
                results.append(addon)
                if len(results) == limit:
                    break
            else:
                # We're excluding this addon because there are no
                # compatible versions. Decrement the total.
                total -= 1

        return Response({
            'results': results,
            'total': total,
        }, template_name=self.template_name)


class ListView(DRFView):

    renderer_classes = (XMLTemplateRenderer, JSONRenderer)
    template_name = 'api/list.xml'

    def get(self, request, api_version, list_type='recommended',
            addon_type='ALL', limit=10, platform='ALL', version=None,
            compat_mode='strict', format=None):
        """
        Find a list of new or featured add-ons.  Filtering is done in Python
        for cache-friendliness and to avoid heavy queries.
        """
        limit = min(MAX_LIMIT, int(limit))
        APP, platform = self.request.APP, platform.lower()
        qs = Addon.objects.listed(APP).exclude(type=amo.ADDON_WEBAPP)
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

        args = (addon_type, limit, APP, platform, version, compat_mode,
                shuffle)
        response = self.create_response(addon_filter(addons, *args))

        # Storing addons within the response to be able to use it later
        # in `self.finalize_response()` as a cache key.
        response.addons = addons
        return response

    def serialize_to_xml(self, results):
        return {'addons': results}

    def serialize_to_json(self, results):
        return [addon_to_dict(a) for a in results]

    def finalize_response(self, request, response, *args, **kwargs):
        """
        Returns a cached response if any, prior to rendering.
        """
        response = super(ListView, self).finalize_response(request, response,
                                                           args, kwargs)
        return cached_with(response.addons, lambda: response.render(),
                           map(encoding.smart_str, args))
