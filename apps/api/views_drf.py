"""
This view is a port of the views.py file (using Piston) to DRF.
It is a work in progress that is supposed to replace the views.py completely.
"""
import urllib
from datetime import date, timedelta

from django.conf import settings
from django.core.urlresolvers import reverse
from django.http import Http404

import commonware.log
from rest_framework.generics import RetrieveAPIView, get_object_or_404
from rest_framework.mixins import RetrieveModelMixin, UpdateModelMixin
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet, ModelViewSet

import amo
from addons.forms import AddonForm
from addons.models import Addon, AddonUser
from amo.decorators import allow_cross_site_request
from amo.models import manual_order
from amo.utils import paginate
import api
from devhub.forms import LicenseForm
from search.views import name_query
from users.models import UserProfile
from versions.forms import XPIForm
from versions.models import Version

from .authentication import RestOAuthAuthentication
from .authorization import (AllowAppOwner, AllowReadOnlyIfPublic,
                            AllowRelatedAppOwner, AnyOf, ByHttpMethod)
from .handlers import _form_error, _xpi_form_error
from .permissions import GroupPermission
from .renderers import JSONRenderer, XMLTemplateRenderer
from .serializers import AddonSerializer, UserSerializer, VersionSerializer
from .utils import addon_to_dict, extract_filters
from .views import (BUFFER, ERROR, MAX_LIMIT, NEW_DAYS, OUT_OF_DATE,
                    addon_filter)

log = commonware.log.getLogger('z.api')


class CORSMixin(object):
    """
    Mixin to enable CORS for DRF API.
    TODO: externalize that mixin (see 984865).
    """
    def finalize_response(self, request, response, *args, **kwargs):
        if not hasattr(request._request, 'CORS'):
            request._request.CORS = self.cors_allowed_methods
        return super(CORSMixin, self).finalize_response(
            request, response, *args, **kwargs)


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
        self.api_version = float(kwargs.get('api_version', 2))

    def get_renderer_context(self):
        context = super(DRFView, self).get_renderer_context()
        context.update({
            'amo': amo,
            'api_version': getattr(self, 'api_version', 0),
        })
        return context

    def create_response(self, results, **kwargs):
        """
        Creates a different Response object given the format type.
        """
        if self.format == 'xml':
            return Response(self.serialize_to_xml(results),
                            template_name=self.template_name, **kwargs)
        else:
            return Response(self.serialize_to_json(results), **kwargs)

    def serialize_to_xml(self, results):
        return {'addons': results}

    def serialize_to_json(self, results):
        return addon_to_dict(results)


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
            addon = Addon.objects.id_or_slug(addon_id).get()
        except Addon.DoesNotExist:
            return Response({'msg': 'Add-on not found!'},
                            template_name=self.error_template_name, status=404)
        if addon.is_disabled:
            return Response({'error_level': ERROR, 'msg': 'Add-on disabled.'},
                            template_name=self.error_template_name, status=404)

        return self.create_response(addon)

    def serialize_to_xml(self, results):
        return {'addon': results}


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

        # We currently filter for status=PUBLIC for all versions. If
        # that changes, the contract for API version 1.5 requires
        # that we continue filtering for it there.
        filters = {
            'app': app_id,
            'status': amo.STATUS_PUBLIC,
            'is_disabled': False,
            'has_version': True,
        }

        # Opts may get overridden by query string filters.
        opts = {
            'addon_type': addon_type,
            'version': version,
        }
        # Specific case for Personas (bug 990768): if we search providing the
        # Persona addon type (9), don't filter on the platform as Personas
        # don't have compatible platforms to filter on.
        if addon_type != '9':
            opts['platform'] = platform

        if self.api_version < 1.5:
            # Fix doubly encoded query strings.
            try:
                query = urllib.unquote(query.encode('ascii'))
            except UnicodeEncodeError:
                # This fails if the string is already UTF-8.
                pass

        query, qs_filters, params = extract_filters(query, opts)

        qs = Addon.search().query(or_=name_query(query))
        filters.update(qs_filters)
        if 'type' not in filters:
            # Filter by ALL types, which is really all types except for apps.
            filters['type__in'] = list(amo.ADDON_SEARCH_TYPES)
        qs = qs.filter(**filters)

        qs = qs[:limit]
        total = qs.count()

        results = []
        for addon in qs:
            compat_version = addon.compatible_version(app_id,
                                                      params['version'],
                                                      params['platform'],
                                                      compat_mode)
            # Specific case for Personas (bug 990768): if we search providing
            # the Persona addon type (9), then don't look for a compatible
            # version.
            if compat_version or addon_type == '9':
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

        args = (addon_type, limit, APP, platform, version, compat_mode,
                shuffle)
        return self.create_response(addon_filter(addons, *args))

    def serialize_to_json(self, results):
        return [addon_to_dict(a) for a in results]


class UserView(RetrieveAPIView, DRFView):

    serializer_class = UserSerializer
    lookup_param = 'email'
    model = UserProfile
    permission_classes = [GroupPermission('API.Users', 'View')]
    authentication_classes = [RestOAuthAuthentication]

    def check_permissions(self, request):
        """
        Do not check permissions in case the user requests his own information.
        """
        lookup = self.kwargs.get(self.lookup_field, None)
        if lookup:
            return super(UserView, self).check_permissions(request)
        else:
            return True

    def get_object(self, queryset=None):
        lookup = self.request.QUERY_PARAMS.get(self.lookup_param, None)
        if lookup:
            queryset = self.filter_queryset(self.get_queryset())
            # Not worth a dedicated DRF filter class given that it's only
            # used for UserProfiles.
            queryset = queryset.filter(deleted=False)
            filter_kwargs = {self.lookup_param: lookup}
            obj = get_object_or_404(queryset, **filter_kwargs)
            self.check_object_permissions(self.request, obj)
            return obj
        else:
            return self.request.amo_user


class AddonsViewSet(DRFView, ModelViewSet):
    serializer_class = AddonSerializer
    queryset = Addon.objects.all()
    authentication_classes = [RestOAuthAuthentication]
    permission_classes = [ByHttpMethod({
        'options': AllowAny,  # Needed for CORS.
        'get': AllowAny,
        'post': IsAuthenticated,
        'put': AnyOf(AllowAppOwner,
                     GroupPermission('Addons', 'Edit')),
        'delete': AnyOf(AllowAppOwner,
                        GroupPermission('Addons', 'Edit')),
    })]
    lookup_url_kwarg = 'addon_id'

    def create(self, request):
        new_file_form = XPIForm(request, request.POST, request.FILES)

        if not new_file_form.is_valid():
            return _xpi_form_error(new_file_form, request)

        # License can be optional.
        license = None
        if 'builtin' in request.POST:
            license_form = LicenseForm(request.POST)
            if not license_form.is_valid():
                return _form_error(license_form)
            license = license_form.save()

        addon = new_file_form.create_addon(license=license)
        if not license:
            # If there is no license, we push you to step
            # 5 so that you can pick one.
            addon.submitstep_set.create(step=5)

        serializer = self.serializer_class(addon)
        return Response(serializer.data, **{
            'status': 201,
            'headers': {
                'Location': reverse('api.addon', kwargs={'addon_id': addon.id})
            }
        })

    def retrieve(self, request, addon_id=None):
        """
        Returns authors who can update an addon (not Viewer role) for addons
        that have not been admin disabled. Optionally provide an addon id.
        """
        ids = (AddonUser.objects.values_list('addon_id', flat=True)
                                .filter(user=request.amo_user,
                                        role__in=[amo.AUTHOR_ROLE_DEV,
                                                  amo.AUTHOR_ROLE_OWNER]))
        qs = (Addon.objects.filter(id__in=ids)
                           .exclude(status=amo.STATUS_DISABLED)
                           .no_transforms())
        if addon_id:
            try:
                addon = qs.get(id=addon_id)
            except Addon.DoesNotExist:
                return Response(status=404)
            serializer = self.serializer_class(addon)
            return Response(serializer.data)

        paginator = paginate(request, qs)
        serializer = self.serializer_class(paginator.object_list, many=True)
        return Response({
            'objects': serializer.data,
            'num_pages': paginator.paginator.num_pages,
            'count': paginator.paginator.count
        })

    def update(self, request, addon_id):
        addon = self.get_object_or_none()
        if addon is None:
            return Response(status=410)

        form = AddonForm(request.DATA, instance=addon)
        if not form.is_valid():
            return _form_error(form)

        serializer = self.serializer_class(form.save())
        return Response(serializer.data)

    def delete(self, request, addon_id):
        addon = self.get_object()
        addon.delete(msg='Deleted via API')
        return Response(status=204)


class VersionsViewSet(CORSMixin, RetrieveModelMixin, UpdateModelMixin,
                      GenericViewSet):
    queryset = Version.objects.exclude(addon__status=amo.STATUS_DELETED)
    serializer_class = VersionSerializer
    authorization_classes = []
    permission_classes = [AnyOf(AllowRelatedAppOwner,
                                GroupPermission('Apps', 'Review'),
                                AllowReadOnlyIfPublic)]
    cors_allowed_methods = ['get', 'patch', 'put']
    lookup_url_kwarg = 'version_id'

    def create(self, request, addon_id):
        addon = get_object_or_404(Addon, id=addon_id)
        new_file_form = XPIForm(request, request.POST, request.FILES,
                                addon=addon)

        if not new_file_form.is_valid():
            return _xpi_form_error(new_file_form, request)

        license = None
        if 'builtin' in request.POST:
            license_form = LicenseForm(request.POST)
            if not license_form.is_valid():
                return _form_error(license_form)
            license = license_form.save()

        v = new_file_form.create_version(license=license)
        serializer = self.serializer_class(v)
        return Response(serializer.data)

    def retrieve(self, request, addon_id, version_id=None):
        if version_id:
            version = self.get_object()
            serializer = self.serializer_class(version)
        else:
            addon = get_object_or_404(Addon, id=addon_id)
            versions = addon.versions.all()
            serializer = self.serializer_class(versions)
        return Response(serializer.data)

    def update(self, request, addon_id, version_id):
        try:
            version = self.get_object()
        except Http404:
            return Response(status=410)

        new_file_form = XPIForm(request, request.DATA, request.FILES,
                                version=version)

        if not new_file_form.is_valid():
            return _xpi_form_error(new_file_form, request)

        license = None
        if 'builtin' in request.DATA:
            license_form = LicenseForm(request.DATA)
            if not license_form.is_valid():
                return _form_error(license_form)
            license = license_form.save()

        v = new_file_form.update_version(license)
        serializer = self.serializer_class(v)
        return Response(serializer.data)

    def delete(self, request, addon_id, version_id):
        version = self.get_object()
        version.delete()
        return Response(status=204)
