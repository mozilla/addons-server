"""
This view is a port of the views.py file (using Piston) to DRF.
It is a work in progress that is supposed to replace the views.py completely.
"""
from django.conf import settings

from rest_framework.response import Response
from rest_framework.views import APIView
from tower import ugettext_lazy

import amo
from addons.models import Addon
from amo.decorators import allow_cross_site_request
import api

from .renderers import JSONRenderer, XMLTemplateRenderer
from .utils import addon_to_dict


ERROR = 'error'
OUT_OF_DATE = ugettext_lazy(
    u'The API version, {0:.1f}, you are using is not valid.  '
    u'Please upgrade to the current version {1:.1f} API.')


class AddonDetailView(APIView):

    renderer_classes = (XMLTemplateRenderer, JSONRenderer)

    @allow_cross_site_request
    def get(self, request, addon_id, api_version, format=None):
        # `settings.URL_FORMAT_OVERRIDE` referers to
        # https://github.com/tomchristie/django-rest-framework/blob/master/rest_framework/negotiation.py#L39
        self.format = format or request.QUERY_PARAMS.get(
            getattr(settings, 'URL_FORMAT_OVERRIDE'), 'xml')
        version = float(api_version)
        # Check valid version.
        if version < api.MIN_VERSION or version > api.MAX_VERSION:
            msg = OUT_OF_DATE.format(version, api.CURRENT_VERSION)
            return Response({'msg': msg}, template_name='api/message.xml',
                            status=403)
        # Retrieve addon.
        try:
            addon = (Addon.objects.id_or_slug(addon_id)
                                  .exclude(type=amo.ADDON_WEBAPP).get())
        except Addon.DoesNotExist:
            return Response({'msg': 'Add-on not found!'},
                            template_name='api/message.xml', status=404)
        if addon.is_disabled:
            return Response({'error_level': ERROR, 'msg': 'Add-on disabled.'},
                            template_name='api/message.xml', status=404)
        # Context.
        if self.format == 'json':
            context = addon_to_dict(addon)
        else:
            context = {
                'api_version': version,
                'addon': addon,
                'amo': amo,
                'version': version
            }
        # `template_name` is only used here for XML format. Refactor this if
        # needed some other way.
        return Response(context, template_name='api/addon_detail.xml')


class LanguageView(APIView):

    renderer_classes = (XMLTemplateRenderer,)

    def get(self, request, api_version):
        addons = Addon.objects.filter(status=amo.STATUS_PUBLIC,
                                      type=amo.ADDON_LPAPP,
                                      appsupport__app=self.request.APP.id,
                                      disabled_by_user=False).order_by('pk')
        return Response({'addons': addons, 'show_localepicker': True,
                         'api_version': api_version},
                        template_name='api/list.xml')
