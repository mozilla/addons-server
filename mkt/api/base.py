import functools
import json
import logging
import sys
import traceback
from collections import defaultdict

from django.conf import settings
from django.core.urlresolvers import reverse
from django.conf.urls.defaults import url
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db.models.sql import EmptyResultSet
from django.http import HttpResponseNotFound

import commonware.log
from rest_framework.decorators import api_view
from rest_framework.mixins import ListModelMixin
from rest_framework.routers import Route, SimpleRouter
from rest_framework.relations import HyperlinkedRelatedField
from rest_framework.response import Response
from rest_framework.serializers import ValidationError
from rest_framework.viewsets import GenericViewSet
from tastypie import fields, http
from tastypie.bundle import Bundle
from tastypie.exceptions import (ImmediateHttpResponse, NotFound,
                                 UnsupportedFormat)
from tastypie.fields import ToOneField
from tastypie.http import HttpConflict
from tastypie.resources import ModelResource, Resource

from access import acl
from translations.fields import PurifiedField, TranslatedField

from .exceptions import AlreadyPurchased, DeserializationError
from .http import HttpTooManyRequests
from .serializers import Serializer

log = commonware.log.getLogger('z.api')
tasty_log = logging.getLogger('django.request.tastypie')


def list_url(name, **kw):
    kw['resource_name'] = name
    return ('api_dispatch_list', kw)


def get_url(name, pk, **kw):
    kw.update({'resource_name': name, 'pk': pk})
    return ('api_dispatch_detail', kw)


def http_error(errorclass, reason, extra_data=None):
    response = errorclass()
    data = {'reason': reason}
    if extra_data:
        data.update(extra_data)
    response.content = json.dumps(data)
    return ImmediateHttpResponse(response)


def handle_500(resource, request, exception):
    response_class = http.HttpApplicationError
    if isinstance(exception, (NotFound, ObjectDoesNotExist)):
        response_class = HttpResponseNotFound

    # Print some nice 500 errors back to the clients if not in debug mode.
    exc_info = sys.exc_info()
    tasty_log.error('%s: %s %s\n%s' % (request.path,
                                       exception.__class__.__name__,
                                       exception,
                                       traceback.format_tb(exc_info[2])),
                    extra={'status_code': 500, 'request': request},
                    exc_info=exc_info)
    data = {
        'error_message': str(exception),
        'error_code': getattr(exception, 'id',
                              exception.__class__.__name__),
        'error_data': getattr(exception, 'data', {})
    }
    serialized = resource.serialize(request, data, 'application/json')
    return response_class(content=serialized,
                          content_type='application/json; charset=utf-8')


class Marketplace(object):
    """
    A mixin with some general Marketplace stuff.
    """

    class Meta(object):
        serializer = Serializer()

    def _handle_500(self, request, exception):
        return handle_500(self, request, exception)

    def dispatch(self, request_type, request, **kwargs):
        # OAuth authentication uses the method in the signature. So we need
        # to store the original method used to sign the request.
        request.signed_method = request.method
        if 'HTTP_X_HTTP_METHOD_OVERRIDE' in request.META:
            request.method = request.META['HTTP_X_HTTP_METHOD_OVERRIDE']

        log.info('Request: %s' % request.META.get('PATH_INFO'))
        ct = request.META.get('CONTENT_TYPE')
        try:
            return (super(Marketplace, self)
                    .dispatch(request_type, request, **kwargs))

        except DeserializationError:
            if ct:
                error = "Unable to deserialize request body as '%s'" % ct
            else:
                error = 'Content-Type header required'
            raise self.non_form_errors((('__all__', error),),)

        except UnsupportedFormat:
            msgs = []
            if ct not in self._meta.serializer.supported_formats:
                msgs.append(('__all__',
                             "Unsupported Content-Type header '%s'" % ct))

            accept = request.META.get('HTTP_ACCEPT')
            if accept and accept != 'application/json':
                msgs.append(('__all__',
                             "Unsupported Accept header '%s'" % accept))

            raise self.non_form_errors(msgs)

        except PermissionDenied:
            # Reraise PermissionDenied as 403, otherwise you get 500.
            raise http_error(http.HttpForbidden, 'Permission denied.')

        except AlreadyPurchased:
            raise http_error(HttpConflict, 'Already purchased app.')

    def non_form_errors(self, error_list):
        """
        Raises passed field errors as an immediate HttpBadRequest response.
        Similar to Marketplace.form_errors, except that it allows you to raise
        form field errors outside of form validation.

        Accepts a list of two-tuples, consisting of a field name and error
        message.

        Example usage:

        errors = []

        if 'app' in bundle.data:
            errors.append(('app', 'Cannot update the app of a rating.'))

        if 'user' in bundle.data:
            errors.append(('user', 'Cannot update the author of a rating.'))

        if errors:
            raise self.non_form_errors(errors)
        """
        errors = defaultdict(list)
        for e in error_list:
            errors[e[0]].append(e[1])
        response = http.HttpBadRequest(json.dumps({'error_message': errors}),
                                       content_type='application/json')
        return ImmediateHttpResponse(response=response)

    def form_errors(self, forms):
        errors = {}
        if not isinstance(forms, list):
            forms = [forms]
        for f in forms:
            # If we've got form objects, get the error object off it.
            # Otherwise assume we've just been passed a form object.
            form_errors = getattr(f, 'errors', f)
            if isinstance(form_errors, list):  # Cope with formsets.
                for e in form_errors:
                    errors.update(e)
                continue
            errors.update(dict(form_errors.items()))

        response = http.HttpBadRequest(json.dumps({'error_message': errors}),
                                       content_type='application/json')
        return ImmediateHttpResponse(response=response)

    def _auths(self):
        auths = self._meta.authentication
        if not isinstance(auths, (list, tuple)):
            auths = [self._meta.authentication]
        return auths

    def is_authenticated(self, request):
        """
        An override of the tastypie Authentication to accept an iterator
        of Authentication methods. If so it will go through in order, when one
        passes, it will use that.

        Any authentication method can still return a HttpResponse to break out
        of the loop if they desire.
        """
        for auth in self._auths():
            log.info('Trying authentication with %s' % auth.__class__.__name__)
            auth_result = auth.is_authenticated(request)

            if isinstance(auth_result, http.HttpResponse):
                raise ImmediateHttpResponse(response=auth_result)

            if auth_result:
                log.info('Logged in using %s' % auth.__class__.__name__)
                return

        raise http_error(http.HttpUnauthorized, 'Authentication required.')

    def get_throttle_identifiers(self, request):
        return set(a.get_identifier(request) for a in self._auths())

    def throttle_check(self, request):
        """
        Handles checking if the user should be throttled.

        Mostly a hook, this uses class assigned to ``throttle`` from
        ``Resource._meta``.
        """
        # Never throttle users with Apps:APIUnthrottled or "safe" requests.
        if (not settings.API_THROTTLE or
            request.method in ('GET', 'HEAD', 'OPTIONS') or
            acl.action_allowed(request, 'Apps', 'APIUnthrottled')):
            return

        identifiers = self.get_throttle_identifiers(request)

        # Check to see if they should be throttled.
        if any(self._meta.throttle.should_be_throttled(identifier)
               for identifier in identifiers):
            # Throttle limit exceeded.
            raise http_error(HttpTooManyRequests,
                             'Throttle limit exceeded.')

    def log_throttled_access(self, request):
        """
        Handles the recording of the user's access for throttling purposes.

        Mostly a hook, this uses class assigned to ``throttle`` from
        ``Resource._meta``.
        """
        request_method = request.method.lower()
        identifiers = self.get_throttle_identifiers(request)
        for identifier in identifiers:
            self._meta.throttle.accessed(identifier,
                                         url=request.get_full_path(),
                                         request_method=request_method)

    def cached_obj_get_list(self, request=None, **kwargs):
        """Do not interfere with cache machine caching."""
        return self.obj_get_list(request=request, **kwargs)

    def cached_obj_get(self, request=None, **kwargs):
        """Do not interfere with cache machine caching."""
        return self.obj_get(request, **kwargs)

    def is_valid(self, bundle, request=None):
        """A simple wrapper to return form errors in the format we want."""
        errors = self._meta.validation.is_valid(bundle, request)
        if errors:
            raise self.form_errors(errors)

    def dehydrate_objects(self, objects, request=None):
        """
        Dehydrates each object using the full_dehydrate and then
        returns the data for each object. This is useful for compound
        results that return sub objects data. If you need request in the
        dehydration, pass that through (eg: accessing region)
        """
        return [self.full_dehydrate(Bundle(obj=o, request=request)).data
                for o in objects]


class MarketplaceResource(Marketplace, Resource):
    """
    Use this if you would like to expose something that is *not* a Django
    model as an API.
    """

    def get_resource_uri(self, *args, **kw):
        return ''


class MarketplaceModelResource(Marketplace, ModelResource):
    """Use this if you would like to expose a Django model as an API."""

    def get_resource_uri(self, bundle_or_obj):
        # Fix until my pull request gets pulled into tastypie.
        # https://github.com/toastdriven/django-tastypie/pull/490
        kwargs = {
            'resource_name': self._meta.resource_name,
        }

        if isinstance(bundle_or_obj, Bundle):
            kwargs['pk'] = bundle_or_obj.obj.pk
        else:
            kwargs['pk'] = bundle_or_obj.pk

        if self._meta.api_name is not None:
            kwargs['api_name'] = self._meta.api_name

        return self._build_reverse_url("api_dispatch_detail", kwargs=kwargs)

    @classmethod
    def should_skip_field(cls, field):
        # We don't want to skip translated fields.
        if isinstance(field, (PurifiedField, TranslatedField)):
            return False

        return True if getattr(field, 'rel') else False

    def get_object_or_404(self, cls, **filters):
        """
        A wrapper around our more familiar get_object_or_404, for when we need
        to get access to an object that isn't covered by get_obj.
        """
        if not filters:
            raise http_error(http.HttpNotFound, 'Not found.')
        try:
            return cls.objects.get(**filters)
        except (cls.DoesNotExist, cls.MultipleObjectsReturned):
            raise http_error(http.HttpNotFound, 'Not found.')

    def get_by_resource_or_404(self, request, **kwargs):
        """
        A wrapper around the obj_get to just get the object.
        """
        try:
            obj = self.obj_get(request, **kwargs)
        except ObjectDoesNotExist:
            raise http_error(http.HttpNotFound, 'Not found.')
        return obj

    def base_urls(self):
        """
        If `slug_lookup` is specified on the Meta of a resource, add
        in an extra resource that allows lookup by that slug field. This
        assumes that the slug won't be all numbers. If the slug is numeric, it
        will hit the pk URL pattern and chaos will ensue.
        """
        if not getattr(self._meta, 'slug_lookup', None):
            return super(MarketplaceModelResource, self).base_urls()

        return super(MarketplaceModelResource, self).base_urls()[:3] + [
            url(r'^(?P<resource_name>%s)/(?P<pk>\d+)/$' %
                    self._meta.resource_name,
                self.wrap_view('dispatch_detail'),
                name='api_dispatch_detail'),
            url(r"^(?P<resource_name>%s)/(?P<%s>[^/<>\"']+)/$" %
                    (self._meta.resource_name, self._meta.slug_lookup),
                self.wrap_view('dispatch_detail'),
                name='api_dispatch_detail')
        ]


class GenericObject(dict):
    """
    tastypie-friendly subclass of dict that allows direct attribute assignment
    of dict items. Best used as `object_class` when not using a `ModelResource`
    subclass.
    """
    def __getattr__(self, name):
        try:
            return self.__getitem__(name)
        except KeyError:
            return None

    def __setattr__(self, name, value):
        self.__setitem__(name, value)


class CORSResource(object):
    """
    A mixin to provide CORS support to your API.
    """

    def method_check(self, request, allowed=None):
        """
        This is the first entry point from dispatch and a place to check CORS.

        It will set a value on the request for the middleware to pick up on
        the response and add in the headers, so that any immediate http
        responses (which are usually errors) get the headers.

        Optionally, you can specify the methods that will be specifying the
        `cors_allowed` attribute on the resource meta. Otherwise, it will use
        the combination of allowed_methods specified on the resource.
        """
        request.CORS = getattr(self._meta, 'cors_allowed', None) or allowed
        return super(CORSResource, self).method_check(request, allowed=allowed)


class PotatoCaptchaResource(object):
    """
    A mixin adding the fields required by PotatoCaptcha to the resource.
    """
    tuber = fields.CharField(attribute='tuber')
    sprout = fields.CharField(attribute='sprout')

    def remove_potato(self, bundle):
        for field in ['tuber', 'sprout']:
            if field in bundle.data:
                del bundle.data[field]
        return bundle

    def alter_detail_data_to_serialize(self, request, data):
        """
        Remove `sprout` from bundle data before returning serialized object to
        the consumer.
        """
        sup = super(PotatoCaptchaResource, self)
        bundle = sup.alter_detail_data_to_serialize(request, data)
        return self.remove_potato(bundle)


def check_potatocaptcha(data):
        if data.get('tuber', False):
            return Response(json.dumps({'tuber': 'Invalid value'}), 400)
        if data.get('sprout', None) != 'potato':
            return Response(json.dumps({'sprout': 'Invalid value'}), 400)


class CompatToOneField(ToOneField):
    """
    Tastypie field to relate a resource to a django-rest-framework view.
    """
    def __init__(self, *args, **kwargs):
        self.url_name = kwargs.pop('url_name', None)
        self.extra_fields = kwargs.pop('extra_fields', None)
        return super(CompatToOneField, self).__init__(*args, **kwargs)

    def dehydrate_related(self, bundle, related_resource):
        uri = reverse(self.url_name, kwargs={'pk': bundle.obj.pk})
        if self.full:
            raise NotImplementedError
        elif self.extra_fields:
            result = {'resource_uri': uri}
            for field in self.extra_fields:
                result[field] = getattr(bundle.obj, field)
            return result
        else:
            return uri

    def get_related_resource(self, related_instance):
        return


class AppRouter(SimpleRouter):
    routes = [
        # List route.
        Route(
            url=r'^{lookup}/{prefix}/$',
            mapping={
                'get': 'list',
                'post': 'create'
            },
            name='{basename}-list',
            initkwargs={'suffix': 'List'}
        ),
        # Detail route.
        Route(
            url=r'^{lookup}/{prefix}/$',
            mapping={
                'get': 'retrieve',
                'put': 'update',
                'post': 'detail_post',
                'patch': 'partial_update',
                'delete': 'destroy'
            },
            name='{basename}-detail',
            initkwargs={'suffix': 'Instance'}
        )
    ]


class SlugRouter(SimpleRouter):

    def get_urls(self):
        """
        Use the registered viewsets to generate a list of URL patterns.

        We can't use the superclass' implementation of get_urls since
        we want slug and pk urls for some resources, and it assumes
        one url per resource.
        """
        ret = []

        for prefix, viewset, basename in self.registry:
            routes = self.get_routes(viewset)

            for route in routes:
                # Only actions which actually exist on the viewset will be
                # bound.
                mapping = self.get_method_map(viewset, route.mapping)
                if not mapping:
                    continue

                # Build the url pattern
                if route.name.endswith('detail'):
                    slug_field = getattr(viewset, 'slug_lookup', None)
                    ret.append(self.create_url(prefix, viewset, basename,
                                               route, mapping, '(?P<pk>\d+)'))
                    if slug_field:
                        ret.append(self.create_url(
                            prefix, viewset, basename, route, mapping,
                            '(?P<%s>[^/<>"\']+)' % (slug_field,)))

                else:
                    ret.append(self.create_url(prefix, viewset, basename,
                                               route, mapping))
        return ret

    def create_url(self, prefix, viewset, basename, route, mapping, lookup=''):
        regex = route.url.format(prefix=prefix, lookup=lookup,
                                 trailing_slash=self.trailing_slash)
        view = viewset.as_view(mapping, **route.initkwargs)
        name = route.name.format(basename=basename)
        return url(regex, view, name=name)


class MarketplaceView(object):
    """
    Base view for DRF views.

    It includes:
    - An implementation of handle_exception() that goes with our custom
      exception handler. It stores the request and originating class in the
      exception before it's handed over the the handler, so that the handler
      can in turn properly propagate the got_request_exception signal if
      necessary.

    - A implementation of paginate_queryset() that goes with our custom
      pagination handler. It does tastypie-like offset pagination instead of
      the default page mechanism.
    """
    def handle_exception(self, exc):
        exc._request = self.request._request
        exc._klass = self.__class__
        return super(MarketplaceView, self).handle_exception(exc)

    def paginate_queryset(self, queryset, page_size=None):
        page_query_param = self.request.QUERY_PARAMS.get(self.page_kwarg)
        offset_query_param = self.request.QUERY_PARAMS.get('offset')

        # If 'offset' (tastypie-style pagination) parameter is present and
        # 'page' isn't, use offset it to find which page to use.
        if page_query_param is None and offset_query_param is not None:
            page_number = int(offset_query_param) / self.get_paginate_by() + 1
            self.kwargs[self.page_kwarg] = page_number
        return super(MarketplaceView, self).paginate_queryset(queryset,
            page_size=page_size)


class CORSMixin(object):
    """
    Mixin to enable CORS for DRF API.
    """
    def finalize_response(self, request, response, *args, **kwargs):
        if not hasattr(request._request, 'CORS'):
            request._request.CORS = self.cors_allowed_methods
        return super(CORSMixin, self).finalize_response(
            request, response, *args, **kwargs)


def cors_api_view(methods):
    def decorator(f):
        @api_view(methods)
        @functools.wraps(f)
        def wrapped(request):
            request._request.CORS = methods
            return f(request)
        return wrapped
    return decorator


class SlugOrIdMixin(object):
    """
    Because the `SlugRouter` is overkill. If the name of your
    `slug` is called something else, override `self.slug_field`.
    """

    def get_object(self, queryset=None):
        pk = self.kwargs.get('pk')
        if pk and not pk.isdigit():
            # If the `pk` contains anything other than a digit, it's a `slug`.
            self.kwargs.update(pk=None, slug=self.kwargs['pk'])
        return super(SlugOrIdMixin, self).get_object(queryset=queryset)


class SilentListModelMixin(ListModelMixin):
    """
    DRF's ListModelMixin that returns a 204_NO_CONTENT rather than flipping a
    500 or 404.
    """

    def list(self, *args, **kwargs):
        try:
            res = super(SilentListModelMixin, self).list(*args, **kwargs)
        except EmptyResultSet:
            return Response([])
        if res.status_code == 404:
            return Response([])
        return res


class AppViewSet(GenericViewSet):

    def initialize_request(self, request, *args, **kwargs):
        """
        Pass the value in the URL through to the form defined on the
        ViewSet, which will populate the app property with the app object.

        You must define a form which will take an app object.
        """
        request = (super(AppViewSet, self)
                   .initialize_request(request, *args, **kwargs))
        self.app = None
        form = self.form({'app': kwargs.get('pk')})
        if form.is_valid():
            self.app = form.cleaned_data['app']
        return request
