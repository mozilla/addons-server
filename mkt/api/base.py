from collections import defaultdict
import json
import logging
import sys
import traceback

from django.conf import settings
from django.conf.urls.defaults import url
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.http import HttpResponseNotFound

from tastypie import fields, http
from tastypie.bundle import Bundle
from tastypie.exceptions import ImmediateHttpResponse, UnsupportedFormat, NotFound
from tastypie.resources import Resource, ModelResource

from access import acl
import commonware.log
from translations.fields import PurifiedField, TranslatedField

from .exceptions import DeserializationError
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
            raise ImmediateHttpResponse(response=http.HttpForbidden())

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

        raise ImmediateHttpResponse(response=http.HttpUnauthorized())

    def throttle_check(self, request):
        """
        Handles checking if the user should be throttled.

        Mostly a hook, this uses class assigned to ``throttle`` from
        ``Resource._meta``.
        """
        # Never throttle users with Apps:APIUnthrottled.
        if (settings.API_THROTTLE and
            not acl.action_allowed(request, 'Apps', 'APIUnthrottled')):
            identifiers = [a.get_identifier(request) for a in self._auths()]

            # Check to see if they should be throttled.
            if any(self._meta.throttle.should_be_throttled(identifier)
                   for identifier in identifiers):
                # Throttle limit exceeded.
                raise ImmediateHttpResponse(response=HttpTooManyRequests())

    def log_throttled_access(self, request):
        """
        Handles the recording of the user's access for throttling purposes.

        Mostly a hook, this uses class assigned to ``throttle`` from
        ``Resource._meta``.
        """
        request_method = request.method.lower()
        identifiers = [a.get_identifier(request) for a in self._auths()]
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
            raise ImmediateHttpResponse(response=http.HttpNotFound())
        try:
            return cls.objects.get(**filters)
        except (cls.DoesNotExist, cls.MultipleObjectsReturned):
            raise ImmediateHttpResponse(response=http.HttpNotFound())

    def get_by_resource_or_404(self, request, **kwargs):
        """
        A wrapper around the obj_get to just get the object.
        """
        try:
            obj = self.obj_get(request, **kwargs)
        except ObjectDoesNotExist:
            raise ImmediateHttpResponse(response=http.HttpNotFound())
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
