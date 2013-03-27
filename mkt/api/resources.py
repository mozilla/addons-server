import json

from django.db import transaction

import commonware.log
from celery_tasktree import TaskTree
from tastypie import fields, http
from tastypie.authorization import Authorization, ReadOnlyAuthorization
from tastypie.constants import ALL
from tastypie.exceptions import ImmediateHttpResponse
from tastypie.resources import ALL_WITH_RELATIONS
from tastypie.serializers import Serializer

import amo
from addons.forms import CategoryFormSet
from addons.models import Addon, AddonUser, Category, Preview
from amo.decorators import write
from amo.utils import no_translation
from constants.applications import DEVICE_TYPES
from files.models import FileUpload, Platform
from lib.metrics import record_action

import mkt
from mkt.api.authentication import (AppOwnerAuthorization,
                                    OptionalOAuthAuthentication,
                                    OwnerAuthorization,
                                    OAuthAuthentication,
                                    PermissionAuthorization,
                                    SharedSecretAuthentication)
from mkt.api.base import MarketplaceModelResource
from mkt.api.forms import (CategoryForm, DeviceTypeForm, NewPackagedForm,
                           PreviewArgsForm, PreviewJSONForm, StatusForm,
                           UploadForm)
from mkt.developers import tasks
from mkt.developers.forms import NewManifestForm, PreviewForm
from mkt.submit.forms import AppDetailsBasicForm
from mkt.webapps.models import Webapp
from reviews.models import Review

log = commonware.log.getLogger('z.api')


class ValidationResource(MarketplaceModelResource):

    class Meta:
        queryset = FileUpload.objects.all()
        fields = ['valid', 'validation']
        list_allowed_methods = ['post']
        detail_allowed_methods = ['get']
        always_return_data = True
        authentication = OptionalOAuthAuthentication()
        authorization = Authorization()
        resource_name = 'validation'
        serializer = Serializer(formats=['json'])

    @write
    @transaction.commit_on_success
    def obj_create(self, bundle, request=None, **kwargs):
        packaged = 'upload' in bundle.data
        form = (NewPackagedForm(bundle.data) if packaged
                else NewManifestForm(bundle.data))

        if not form.is_valid():
            raise self.form_errors(form)

        if not packaged:
            upload = FileUpload.objects.create(
                user=getattr(request, 'amo_user', None))
            # The hosted app validator is pretty fast.
            tasks.fetch_manifest(form.cleaned_data['manifest'], upload.pk)
        else:
            upload = form.file_upload
            # The packaged app validator is much heavier.
            tasks.validator.delay(upload.pk)

        # This is a reget of the object, we do this to get the refreshed
        # results if not celery delayed.
        bundle.obj = FileUpload.uncached.get(pk=upload.pk)
        log.info('Validation created: %s' % bundle.obj.pk)
        return bundle

    @write
    def obj_get(self, request=None, **kwargs):
        # Until the perms branch lands, this is the only way to lock
        # permissions down on gets, since the object doesn't actually
        # get passed through to OwnerAuthorization.
        try:
            obj = FileUpload.objects.get(pk=kwargs['pk'])
        except FileUpload.DoesNotExist:
            raise ImmediateHttpResponse(response=http.HttpNotFound())

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


class AppResource(MarketplaceModelResource):
    previews = fields.ToManyField('mkt.api.resources.PreviewResource',
                                  'previews', readonly=True)

    class Meta:
        queryset = Addon.objects.filter(type=amo.ADDON_WEBAPP)
        fields = ['id', 'name', 'description', 'device_types',
                  'homepage', 'privacy_policy',
                  'status', 'summary', 'support_email', 'support_url',
                  'categories']
        list_allowed_methods = ['get', 'post']
        allowed_methods = ['get', 'put']
        always_return_data = True
        authentication = OptionalOAuthAuthentication()
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
        bundle.obj = Addon.from_upload(form.obj, plats,
                                       is_packaged=form.is_packaged)
        AddonUser(addon=bundle.obj, user=request.amo_user).save()

        self._icons_and_images(bundle.obj)
        record_action('app-submitted', request, {'app-id': bundle.obj.pk})

        log.info('App created: %s' % bundle.obj.pk)
        return bundle

    def _icons_and_images(self, bundle_obj):
        pipeline = TaskTree()
        pipeline.push(tasks.fetch_icon, args=[bundle_obj])
        pipeline.push(tasks.generate_image_assets, args=[bundle_obj])
        pipeline.apply_async()

    @write
    def obj_get(self, request=None, **kwargs):
        obj = self.get_and_check_ownership(request, allow_anon=True, **kwargs)
        log.info('App retreived: %s' % obj.pk)
        return obj

    def devices(self, data):
        with no_translation():
            names = dict([(n.api_name, n.id)
                          for n in DEVICE_TYPES.values()])
        filtered = [names.get(n, n) for n in data.get('device_types', [])]
        return {'device_types': filtered}

    def formset(self, data):
        cats = data.pop('categories', [])
        return {'form-TOTAL_FORMS': 1,
                'form-INITIAL_FORMS': 1,
                'form-MAX_NUM_FORMS': '',
                'form-0-categories': cats}

    def get_and_check_ownership(self, request, allow_anon=False, **kwargs):
        try:
            # Use queryset, not get_object_list to ensure a distinction
            # between a 404 and a 403.
            #
            # For reasons I haven't been able to figure out, accessing the
            # queryset at this point will get you the locale of the class
            # when it was initialized, which means that the locale gets
            # set and results in bug 854505.
            obj = Addon.objects.filter(type=amo.ADDON_WEBAPP).get(**kwargs)
        except Addon.DoesNotExist:
            raise ImmediateHttpResponse(response=http.HttpNotFound())

        # If it's public, just return it.
        if allow_anon and obj.is_public():
            return obj

        # Now do the final check to see if you are allowed to see it and
        # return a 403 if you can't.
        if not AppOwnerAuthorization().is_authorized(request, object=obj):
            raise ImmediateHttpResponse(response=http.HttpForbidden())
        return obj

    @write
    @transaction.commit_on_success
    def obj_update(self, bundle, request, **kwargs):
        data = bundle.data
        obj = self.get_and_check_ownership(request, **kwargs)

        data['app_slug'] = data.get('app_slug', obj.app_slug)
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
        bundle.data['app_slug'] = obj.app_slug
        bundle.data['premium_type'] = amo.ADDON_PREMIUM_API[obj.premium_type]
        bundle.data['categories'] = [c.pk for c in obj.categories.all()]
        with no_translation():
            bundle.data['device_types'] = [n.api_name
                                           for n in obj.device_types]
        bundle.data['app_type'] = obj.app_type
        return bundle

    def get_object_list(self, request):
        if not request.amo_user:
            log.info('Anonymous listing not allowed')
            raise ImmediateHttpResponse(response=http.HttpForbidden())
        return Addon.objects.filter(type=amo.ADDON_WEBAPP,
                                    authors=request.amo_user)


class StatusResource(MarketplaceModelResource):

    class Meta:
        queryset = Addon.objects.filter(type=amo.ADDON_WEBAPP)
        fields = ['status', 'disabled_by_user']
        list_allowed_methods = []
        allowed_methods = ['patch', 'get']
        always_return_data = True
        authentication = OAuthAuthentication()
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

    @write
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


class CategoryResource(MarketplaceModelResource):

    class Meta:
        queryset = Category.objects.filter(type=amo.ADDON_WEBAPP,
                                           weight__gte=0)
        list_allowed_methods = ['get']
        allowed_methods = ['get']
        fields = ['name', 'id', 'slug']
        always_return_data = True
        resource_name = 'category'
        serializer = Serializer(formats=['json'])


class PreviewResource(MarketplaceModelResource):
    image_url = fields.CharField(attribute='image_url', readonly=True)
    thumbnail_url = fields.CharField(attribute='thumbnail_url', readonly=True)

    class Meta:
        queryset = Preview.objects.all()
        list_allowed_methods = ['post']
        allowed_methods = ['get', 'delete']
        always_return_data = True
        fields = ['id', 'filetype']
        authentication = OAuthAuthentication()
        authorization = OwnerAuthorization()
        resource_name = 'preview'
        filtering = {'addon': ALL_WITH_RELATIONS}

    def obj_create(self, bundle, request, **kwargs):
        # Ensure that people don't pass strings through.
        args = PreviewArgsForm(request.GET)
        if not args.is_valid():
            raise self.form_errors(args)

        addon = self.get_object_or_404(Addon,
                                       pk=args.cleaned_data['app'],
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


def collect_replies(bundle):
    return Review.objects.filter(reply_to=bundle.obj.pk)


class RatingResource(MarketplaceModelResource):

    app = fields.ToOneField(AppResource, 'addon', readonly=True)
    replies = fields.ToManyField('self', collect_replies,
                                 readonly=True, full=True, null=True)

    class Meta:
        # Unfortunately, the model class name for ratings is "Review".
        queryset = Review.objects.valid()
        resource_name = 'rating'
        detail_allowed_methods = ['get', 'delete']
        list_allowed_methods = ['get']
        # TODO figure out authentication/authorization soon.
        authentication = (OAuthAuthentication(), SharedSecretAuthentication())
        authorization = Authorization()
        fields = ['app', 'user', 'replies', 'rating', 'title',
                  'body', 'editorreview']

        filtering = {
            'app': ('exact',),
            'user': ('exact',),
            'pk': ('exact',),
            'is_latest': ('exact',),
            'created': ALL,
        }

        ordering = ['created']

    def get_object_list(self, request):
        qs = MarketplaceModelResource.get_object_list(self, request)
        # Mature regions show only reviews from within that region.
        if not request.REGION.adolescent:
            qs = qs.filter(client_data__region=request.REGION.id)
        return qs

    def obj_delete(self, request, **kwargs):
        obj = self.get_by_resource_or_404(request, **kwargs)
        if not (AppOwnerAuthorization().is_authorized(request,
                                                      object=obj.addon)
                or OwnerAuthorization().is_authorized(request, object=obj)
                or PermissionAuthorization('Users', 'Edit'
                                           ).is_authorized(request)
                or PermissionAuthorization('Addons', 'Edit'
                                           ).is_authorized(request)):
            raise ImmediateHttpResponse(response=http.HttpForbidden())

        log.info('Rating %s deleted from addon %s' % (obj.pk, obj.addon.pk))
        return super(RatingResource, self).obj_delete(request, **kwargs)

    def alter_list_data_to_serialize(self, request, data):
        if 'app' in request.GET:
            addon = Addon.objects.get(pk=request.GET['app'])
            data['info'] = {
                'average': addon.average_rating,
                'slug': addon.app_slug
                }

            filters = dict(addon=addon, user=request.user)
            if addon.is_packaged:
                filters['version'] = addon.current_version
            existing_review = Review.objects.valid().filter(**filters).exists()
            data['user'] = {'can_rate': not addon.has_author(request.user),
                            'has_rated': existing_review}
        return data


class FeaturedHomeResource(AppResource):

    class Meta(AppResource.Meta):
        resource_name = 'featured/home'
        allowed_methods = []
        detail_allowed_methods = []
        list_allowed_methods = ['get']
        authorization = ReadOnlyAuthorization()
        authentication = OptionalOAuthAuthentication()

    def get_resource_uri(self, bundle):
        # At this time we don't have an API to the Webapp details.
        return None

    def get_list(self, request=None, **kwargs):
        rg = request.GET
        _get = {
            'region': mkt.regions.REGIONS_DICT.get(rg.get('region'),
                                                   mkt.regions.WORLDWIDE),
            'limit': rg.get('limit', 12),
            'mobile': rg.get('dev') in ('android', 'fxos'),
            'tablet': rg.get('dev') != 'desktop' and rg.get('scr') == 'wide',
            'gaia': rg.get('dev') == 'fxos',
        }

        qs = Webapp.featured(**_get)
        paginator = self._meta.paginator_class(
            request.GET, qs, resource_uri=self.get_resource_list_uri(),
            limit=self._meta.limit)
        page = paginator.page()
        objs = [self.build_bundle(obj=obj, request=request)
                for obj in page['objects']]
        page['objects'] = [self.full_dehydrate(bundle) for bundle in objs]

        return self.create_response(request, page)
