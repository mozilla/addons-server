import json

from django.db import transaction

import commonware.log
from tastypie import http
from tastypie.exceptions import ImmediateHttpResponse
from tastypie import fields
from tastypie.serializers import Serializer
from tastypie.resources import ALL_WITH_RELATIONS

from addons.forms import CategoryFormSet, DeviceTypeForm
from addons.models import AddonUser, Category, Preview
import amo
from amo.decorators import write
from amo.utils import no_translation
from constants.applications import DEVICE_TYPES
from files.models import FileUpload, Platform
from mkt.api.authentication import (AppOwnerAuthorization, OwnerAuthorization,
                                    MarketplaceAuthentication)
from mkt.api.base import MarketplaceResource
from mkt.api.forms import CategoryForm, UploadForm, StatusForm
from mkt.developers import tasks
from mkt.developers.forms import NewManifestForm
from mkt.developers.forms import PreviewForm
from mkt.api.forms import PreviewJSONForm
from mkt.webapps.models import Addon
from mkt.submit.forms import AppDetailsBasicForm

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
        serializer = Serializer(formats=['json'])

    @write
    @transaction.commit_on_success
    def obj_create(self, bundle, request=None, **kwargs):
        form = NewManifestForm(bundle.data)
        if not form.is_valid():
            raise self.form_errors(form)

        upload = FileUpload.objects.create(user=amo.get_user())
        tasks.fetch_manifest(form.cleaned_data['manifest'], upload.pk)
        bundle.obj = FileUpload.objects.get(pk=upload.pk)
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
            raise ImmediateHttpResponse(response=http.HttpForbidden())

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
    previews = fields.ToManyField('mkt.api.resources.PreviewResource',
                                  'previews', readonly=True)

    class Meta:
        queryset = Addon.objects.filter(type=amo.ADDON_WEBAPP)
        fields = ['id', 'name', 'description', 'device_types',
                  'homepage', 'privacy_policy',
                  'status', 'summary', 'support_email', 'support_url',
                  'categories']
        list_allowed_methods = ['post']
        allowed_methods = ['get', 'put']
        always_return_data = True
        authentication = MarketplaceAuthentication()
        authorization = AppOwnerAuthorization()
        resource_name = 'app'
        serializer = Serializer(formats=['json'])

    @write
    @transaction.commit_on_success
    def obj_create(self, bundle, request, **kwargs):
        form = UploadForm(bundle.data)
        if not form.is_valid():
            raise self.form_errors(form)

        if not (OwnerAuthorization()
                .is_authorized(request, object=form.obj)):
            raise ImmediateHttpResponse(response=http.HttpForbidden())

        plats = [Platform.objects.get(id=amo.PLATFORM_ALL.id)]

        # Create app, user and fetch the icon.
        bundle.obj = Addon.from_upload(form.obj, plats)
        AddonUser(addon=bundle.obj, user=request.amo_user).save()
        tasks.fetch_icon.delay(bundle.obj)
        log.info('App created: %s' % bundle.obj.pk)
        return bundle

    def obj_get(self, request=None, **kwargs):
        obj = super(AppResource, self).obj_get(request=request, **kwargs)
        if not AppOwnerAuthorization().is_authorized(request, object=obj):
            raise ImmediateHttpResponse(response=http.HttpForbidden())

        log.info('App retreived: %s' % obj.pk)
        return obj

    def devices(self, data):
        with no_translation():
            names = dict([(n.class_name, n.id)
                          for n in DEVICE_TYPES.values()])
        filtered = [names.get(n, n) for n in data.get('device_types', [])]
        return {'device_types': filtered}

    def formset(self, data):
        cats = data.pop('categories', [])
        return {'form-TOTAL_FORMS': 1,
                'form-INITIAL_FORMS': 1,
                'form-MAX_NUM_FORMS': '',
                'form-0-categories': cats}

    @write
    @transaction.commit_on_success
    def obj_update(self, bundle, request, **kwargs):
        data = bundle.data
        try:
            obj = self.get_object_list(bundle.request).get(**kwargs)
        except Addon.DoesNotExist:
            raise ImmediateHttpResponse(response=http.HttpNotFound())

        if not AppOwnerAuthorization().is_authorized(request, object=obj):
            raise ImmediateHttpResponse(response=http.HttpForbidden())

        data['slug'] = data.get('slug', obj.app_slug)
        data.update(self.formset(data))
        data.update(self.devices(data))

        forms = [AppDetailsBasicForm(data, instance=obj, request=request),
                 DeviceTypeForm(data, addon=obj),
                 CategoryFormSet(data, addon=obj, request=request),
                 CategoryForm({'categories': data['form-0-categories']})]

        valid = all([f.is_valid() for f in forms])
        if not valid:
            raise self.form_errors(forms)

        forms[0].save(obj)
        forms[1].save(obj)
        forms[2].save()
        log.info('App updated: %s' % obj.pk)
        bundle.obj = obj
        return bundle

    def dehydrate(self, bundle):
        obj = bundle.obj
        bundle.data['slug'] = obj.app_slug
        bundle.data['premium_type'] = amo.ADDON_PREMIUM_API[obj.premium_type]
        bundle.data['categories'] = [c.pk for c in obj.categories.all()]
        with no_translation():
            bundle.data['device_types'] = [str(n.name).lower()
                                            for n in obj.device_types]
        return bundle


class StatusResource(MarketplaceResource):

    class Meta:
        queryset = Addon.objects.filter(type=amo.ADDON_WEBAPP)
        fields = ['status', 'disabled_by_user']
        list_allowed_methods = []
        allowed_methods = ['patch', 'get']
        always_return_data = True
        authentication = MarketplaceAuthentication()
        authorization = AppOwnerAuthorization()
        resource_name = 'status'
        serializer = Serializer(formats=['json'])

    @write
    @transaction.commit_on_success
    def obj_update(self, bundle, request, **kwargs):
        try:
            obj = self.get_object_list(bundle.request).get(**kwargs)
        except Addon.DoesNotExist:
            raise ImmediateHttpResponse(response=http.HttpNotFound())

        if not AppOwnerAuthorization().is_authorized(request, object=obj):
            raise ImmediateHttpResponse(response=http.HttpForbidden())

        form = StatusForm(bundle.data, instance=obj)
        if not form.is_valid():
            raise self.form_errors(form)

        form.save()
        log.info('App status updated: %s' % obj.pk)
        bundle.obj = obj
        return bundle

    def obj_get(self, request=None, **kwargs):
        obj = super(StatusResource, self).obj_get(request=request, **kwargs)
        if not AppOwnerAuthorization().is_authorized(request, object=obj):
            raise ImmediateHttpResponse(response=http.HttpForbidden())

        log.info('App status retreived: %s' % obj.pk)
        return obj

    def dehydrate_status(self, bundle):
        return amo.STATUS_CHOICES_API[int(bundle.data['status'])]

    def hydrate_status(self, bundle):
        return amo.STATUS_CHOICES_API_LOOKUP[int(bundle.data['status'])]


class CategoryResource(MarketplaceResource):

    class Meta:
        queryset = Category.objects.filter(type=amo.ADDON_WEBAPP,
                                           weight__gte=0)
        list_allowed_methods = ['get']
        allowed_methods = ['get']
        fields = ['name', 'id']
        always_return_data = True
        resource_name = 'category'
        serializer = Serializer(formats=['json'])


class PreviewResource(MarketplaceResource):
    image_url = fields.CharField(attribute='image_url', readonly=True)
    thumbnail_url = fields.CharField(attribute='thumbnail_url', readonly=True)

    class Meta:
        queryset = Preview.objects.all()
        list_allowed_methods = ['post']
        allowed_methods = ['get', 'delete']
        always_return_data = True
        fields = ['id', 'filetype']
        authentication = MarketplaceAuthentication()
        authorization = OwnerAuthorization()
        resource_name = 'preview'
        filtering = {'addon': ALL_WITH_RELATIONS}

    def obj_create(self, bundle, request, **kwargs):
        addon = self.get_object_or_404(Addon,
                                       pk=request.GET.get('app'),
                                       type=amo.ADDON_WEBAPP)
        if not AppOwnerAuthorization().is_authorized(request, object=addon):
            raise ImmediateHttpResponse(response=http.HttpForbidden())

        data_form = PreviewJSONForm(bundle.data)
        if not data_form.is_valid():
            raise self.form_errors(data_form)

        form = PreviewForm(data_form.cleaned_data)
        if not form.is_valid():
            raise self.form_errors(form)

        form.save(addon)
        bundle.obj = form.instance
        log.info('Preview created: %s' % bundle.obj.pk)
        return bundle

    def obj_delete(self, request, **kwargs):
        obj = self.get_by_resource_or_404(request, **kwargs)
        if not AppOwnerAuthorization().is_authorized(request,
                                                     object=obj.addon):
            raise ImmediateHttpResponse(response=http.HttpForbidden())

        log.info('Preview deleted: %s' % obj.pk)
        return super(PreviewResource, self).obj_delete(request, **kwargs)

    def obj_get(self, request=None, **kwargs):
        obj = super(PreviewResource, self).obj_get(request=request, **kwargs)
        if not AppOwnerAuthorization().is_authorized(request,
                                                     object=obj.addon):
            raise ImmediateHttpResponse(response=http.HttpForbidden())

        log.info('Preview retreived: %s' % obj.pk)
        return obj

    def dehydrate(self, bundle):
        # Returning an image back to the user isn't useful, let's stop that.
        if 'file' in bundle.data:
            del bundle.data['file']
        return bundle
