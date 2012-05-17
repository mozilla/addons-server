import json

from django.forms import ValidationError

import commonware.log
from tastypie import http
from tastypie.exceptions import ImmediateHttpResponse

from files.models import FileUpload
from mkt.developers import tasks
from mkt.developers.forms import NewManifestForm
from mkt.api.authentication import (OwnerAuthorization,
                                    MarketplaceAuthentication)
from mkt.api.base import MarketplaceResource

log = commonware.log.getLogger('z.api')


class ValidationResource(MarketplaceResource):

    class Meta:
        queryset = FileUpload.objects.all()
        fields = ['valid', 'validation']
        list_allowed_methods = ['post']
        allowed_methods = ['get']
        always_return_data = True
        authentication = MarketplaceAuthentication()
        # This will return that anyone can do anything because objects
        # don't always get passed the authorization handler.
        authorization = OwnerAuthorization()
        resource_name = 'validation'

    def obj_create(self, bundle, request=None, **kwargs):
        form = NewManifestForm(bundle.data)
        if not form.is_valid():
            raise ValidationError(self.form_errors(form))

        bundle.obj = FileUpload.objects.create()
        tasks.fetch_manifest.delay(form.cleaned_data['manifest'],
                                   bundle.obj.pk)
        log.info('Validation created: %s' % bundle.obj.pk)
        return bundle

    def obj_get(self, request=None, **kwargs):
        # Until the perms branch lands, this is the only way to lock
        # permissions down on gets, since the object doesn't actually
        # get passed through to OwnerAuthorization.
        try:
            obj = FileUpload.objects.get(pk=kwargs['pk'])
        except FileUpload.DoesNotExist:
            raise ImmediateHttpResponse(response=http.HttpNotFound())

        if not OwnerAuthorization().is_authorized(request, object=obj):
            raise ImmediateHttpResponse(response=http.HttpUnauthorized())

        log.info('Validation retreived: %s' % obj.pk)
        return obj

    def dehydrate_validation(self, bundle):
        validation = bundle.data['validation']
        return json.loads(validation) if validation else validation

    def dehydrate(self, bundle):
        bundle.data['id'] = bundle.obj.pk
        bundle.data['processed'] = (bool(bundle.obj.valid or
                                         bundle.obj.validation))
        return bundle
