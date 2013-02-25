import json

from django.core.exceptions import ObjectDoesNotExist

from tastypie import http
from tastypie.bundle import Bundle
from tastypie.exceptions import ImmediateHttpResponse
from tastypie.resources import ModelResource

import commonware.log
import oauth2
from translations.fields import PurifiedField, TranslatedField

log = commonware.log.getLogger('z.api')


class MarketplaceResource(ModelResource):

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

    def form_errors(self, forms):
        errors = {}
        if not isinstance(forms, list):
            forms = [forms]
        for f in forms:
            if isinstance(f.errors, list):  # Cope with formsets.
                for e in f.errors:
                    errors.update(e)
                continue
            errors.update(dict(f.errors.items()))

        response = http.HttpBadRequest(json.dumps({'error_message': errors}),
                                       content_type='application/json')
        return ImmediateHttpResponse(response=response)

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

    def dispatch(self, request_type, request, **kwargs):
        try:
            auth = (oauth2.Request._split_header(
                    request.META.get('HTTP_AUTHORIZATION', '')))
            name = auth.get('oauth_consumer_key', 'none')
        except (AttributeError, IndexError):
            # Problems parsing the header.
            name = 'error'
        log.debug('%s:%s:%s' % (
                  request.META['REQUEST_METHOD'], request.path, name))
        return (super(MarketplaceResource, self)
                .dispatch(request_type, request, **kwargs))


class CORSResource(MarketplaceResource):

    def method_check(self, request, allowed=None):
        """
        This is the first entry point from dispatch and a place to check CORS.

        It will set a value on the request for the middleware to pick up on
        the response and add in the headers, so that any immediate http
        responses (which are usually errors) get the headers.
        """
        request.CORS = allowed
        return super(CORSResource, self).method_check(request, allowed=allowed)
