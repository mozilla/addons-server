import json

from django.db import transaction
from django.forms import ValidationError

import commonware.log
from tastypie import http
from tastypie.exceptions import ImmediateHttpResponse

from addons.models import AddonUser, Category
import amo
from amo.decorators import write
from files.models import FileUpload, Platform
from mkt.api.authentication import (AppOwnerAuthorization, OwnerAuthorization,
                                    MarketplaceAuthentication)
from mkt.api.base import MarketplaceResource
from mkt.api.forms import UploadForm
from mkt.developers import tasks
from mkt.developers.forms import NewManifestForm
from mkt.webapps.models import Webapp
from mkt.submit.forms import AppDetailsBasicForm
from addons.forms import CategoryFormSet

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

    @write
    @transaction.commit_on_success
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


class AppResource(MarketplaceResource):

    class Meta:
        queryset = Webapp.objects.all().no_transforms()
        fields = ['id', 'name', 'description', 'homepage', 'status', 'summary',
                  'support_email', 'support_url', 'categories']
        list_allowed_methods = ['post']
        allowed_methods = ['get', 'put']
        always_return_data = True
        authentication = MarketplaceAuthentication()
        authorization = AppOwnerAuthorization()
        resource_name = 'app'

    @write
    @transaction.commit_on_success
    def obj_create(self, bundle, request, **kwargs):
        form = UploadForm(bundle.data)
        if not form.is_valid():
            raise ValidationError(self.form_errors(form))

        if not (OwnerAuthorization()
                .is_authorized(request, object=form.obj)):
            raise ImmediateHttpResponse(response=http.HttpUnauthorized())

        plats = [Platform.objects.get(id=amo.PLATFORM_ALL.id)]

        # Create app, user and fetch the icon.
        bundle.obj = Webapp.from_upload(form.obj, plats)
        AddonUser(addon=bundle.obj, user=request.amo_user).save()
        tasks.fetch_icon.delay(bundle.obj)
        log.info('App created: %s' % bundle.obj.pk)
        return bundle

    def obj_get(self, request=None, **kwargs):
        obj = super(AppResource, self).obj_get(request=request, **kwargs)
        if not AppOwnerAuthorization().is_authorized(request, object=obj):
            raise ImmediateHttpResponse(response=http.HttpUnauthorized())

        log.info('App retreived: %s' % obj.pk)
        return obj

    def formset(self, data):
        cats = data.pop('categories', [])
        return {'form-TOTAL_FORMS': 1,
                'form-INITIAL_FORMS': 1,
                'form-MAX_NUM_FORMS': '',
                'form-0-categories': cats}

    @write
    @transaction.commit_on_success
    def obj_update(self, bundle, request, **kwargs):
        try:
            bundle.obj = self.get_object_list(bundle.request).get(**kwargs)
        except Webapp.DoesNotExist:
            raise ImmediateHttpResponse(response=http.HttpNotFound())

        if not (AppOwnerAuthorization()
                .is_authorized(request, object=bundle.obj)):
            raise ImmediateHttpResponse(response=http.HttpUnauthorized())

        bundle.data['slug'] = bundle.data.get('slug', bundle.obj.app_slug)
        bundle.data.update(self.formset(bundle.data))

        forms = [AppDetailsBasicForm(bundle.data, instance=bundle.obj,
                                     request=request),
                 CategoryFormSet(bundle.data, addon=bundle.obj,
                                 request=request)]
        valid = all([f.is_valid() for f in forms])
        if not valid:
            raise ValidationError(self.form_errors(forms))

        forms[0].save(bundle.obj)
        forms[1].save()
        return bundle

    def dehydrate(self, bundle):
        obj = bundle.obj
        bundle.data['slug'] = obj.app_slug
        bundle.data['premium_type'] = amo.ADDON_PREMIUM_API[obj.premium_type]
        bundle.data['categories'] = [c.pk for c in obj.categories.all()]
        return bundle


class CategoryResource(MarketplaceResource):

    class Meta:
        queryset = Category.objects.filter(type=amo.ADDON_WEBAPP)
        list_allowed_methods = ['get']
        allowed_methods = ['get']
        fields = ['name', 'id']
        always_return_data = True
        authentication = MarketplaceAuthentication()
        resource_name = 'category'
