import json

from django.conf import settings, urls
from django.db import transaction
from django.db.models import Q
from django.views import debug

import commonware.log
import waffle
from celery_tasktree import TaskTree
from tastypie import fields, http
from tastypie.authorization import Authorization
from tastypie.exceptions import ImmediateHttpResponse
from tastypie.resources import ALL_WITH_RELATIONS
from tastypie.serializers import Serializer
from tastypie.throttle import CacheThrottle
from tastypie.utils import trailing_slash

import amo
from amo.utils import memoize
from addons.forms import CategoryFormSet
from addons.models import Addon, AddonUser, Category, Preview, Webapp
from amo.decorators import write
from amo.utils import no_translation
from constants.applications import DEVICE_TYPES
from files.models import FileUpload, Platform
from lib.metrics import record_action
from market.models import AddonPremium, Price

from mkt.api.authentication import (OAuthAuthentication,
                                    OptionalOAuthAuthentication)
from mkt.api.authorization import AppOwnerAuthorization, OwnerAuthorization
from mkt.api.base import (CORSResource, GenericObject,
                          MarketplaceModelResource, MarketplaceResource)
from mkt.api.forms import (CategoryForm, DeviceTypeForm, NewPackagedForm,
                           PreviewArgsForm, PreviewJSONForm, StatusForm,
                           UploadForm)
from mkt.api.http import HttpLegallyUnavailable
from mkt.carriers import CARRIER_MAP, CARRIERS, get_carrier_id
from mkt.developers import tasks
from mkt.developers.forms import NewManifestForm, PreviewForm
from mkt.regions import get_region, get_region_id, REGIONS_DICT
from mkt.submit.forms import AppDetailsBasicForm
from mkt.webapps.models import get_excluded_in
from mkt.webapps.utils import app_to_dict, update_with_reviewer_data

log = commonware.log.getLogger('z.api')


class ValidationResource(CORSResource, MarketplaceModelResource):

    class Meta(MarketplaceModelResource.Meta):
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


class AppResource(CORSResource, MarketplaceModelResource):
    payment_account = fields.ToOneField('mkt.developers.api.AccountResource',
                                        'app_payment_account', null=True)
    premium_type = fields.IntegerField(null=True)
    previews = fields.ToManyField('mkt.api.resources.PreviewResource',
                                  'previews', readonly=True)
    upsold = fields.ToOneField('mkt.api.resources.AppResource', 'upsold',
                               null=True)

    class Meta(MarketplaceModelResource.Meta):
        queryset = Webapp.objects.all()  # Gets overriden in dispatch.
        fields = ['categories', 'description', 'device_types', 'homepage',
                  'id', 'name', 'payment_account', 'premium_type',
                  'status', 'summary', 'support_email', 'support_url']
        list_allowed_methods = ['get', 'post']
        detail_allowed_methods = ['get', 'put', 'delete']
        always_return_data = True
        authentication = OptionalOAuthAuthentication()
        authorization = AppOwnerAuthorization()
        resource_name = 'app'
        serializer = Serializer(formats=['json'])
        slug_lookup = 'app_slug'
        # Throttle users without Apps:APIUnthrottled at 10 POST requests/day.
        throttle = CacheThrottle(throttle_at=10, timeframe=60 * 60 * 24)

    def dispatch(self, request_type, request, **kwargs):
        # Using `Webapp.objects.all()` here forces a new queryset, which for
        # now avoids bug 854505. We're also using this to filter by flagged
        # apps.
        self._meta.queryset_base = Webapp.objects.all()
        self._meta.queryset = self._meta.queryset_base.exclude(
            id__in=get_excluded_in(REGIONS_DICT[get_region()].id))
        return super(AppResource, self).dispatch(request_type, request,
                                                 **kwargs)

    @write
    @transaction.commit_on_success
    def obj_create(self, bundle, request, **kwargs):
        form = UploadForm(bundle.data)

        if not request.amo_user.read_dev_agreement:
            log.info(u'Attempt to use API without dev agreement: %s'
                     % request.amo_user.pk)
            response = http.HttpUnauthorized()
            response.content = json.dumps({'reason':
                                           'Terms of service not accepted.'})
            raise ImmediateHttpResponse(response=response)

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

    def log_throttled_access(self, request):
        """
        Only throttle POST requests.
        """
        if request.method == 'POST':
            super(AppResource, self).log_throttled_access(request)

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
            obj = self._meta.queryset.get(**kwargs)
        except self._meta.object_class.DoesNotExist:
            unavail = self._meta.queryset_base.filter(**kwargs).exists()
            if unavail:
                raise ImmediateHttpResponse(response=HttpLegallyUnavailable())
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
    def obj_delete(self, request, **kwargs):
        app = self.get_and_check_ownership(request, **kwargs)
        app.delete('Removed via API')

    @write
    @transaction.commit_on_success
    def obj_update(self, bundle, request, **kwargs):
        data = bundle.data
        obj = self.get_and_check_ownership(request, **kwargs)
        bundle.obj = obj
        data['app_slug'] = data.get('app_slug', obj.app_slug)
        data.update(self.formset(data))
        data.update(self.devices(data))
        self.update_premium_type(bundle)

# TODO: renable when regions are sorted out.
#        if 'regions' in data:
#            data['regions'] = [REGIONS_DICT[r['slug']].id for r in data['regions']
#                               if r.get('slug') in REGIONS_DICT]

        forms = [AppDetailsBasicForm(data, instance=obj, request=request),
                 DeviceTypeForm(data, addon=obj),
#                 RegionForm(data, product=obj),
                 CategoryFormSet(data, addon=obj, request=request),
                 CategoryForm({'categories': data['form-0-categories']})]

        valid = all([f.is_valid() for f in forms])
        if not valid:
            raise self.form_errors(forms)
        forms[0].save(obj)
        forms[1].save(obj)
        forms[2].save()
#        forms[3].save()
        log.info('App updated: %s' % obj.pk)

        return bundle

    def update_premium_type(self, bundle):
        self.hydrate_premium_type(bundle)
        if bundle.obj.premium_type in (amo.ADDON_FREE, amo.ADDON_FREE_INAPP):
            return

        ap = AddonPremium.objects.safer_get_or_create(addon=bundle.obj)[0]
        if not bundle.data.get('price') or not Price.objects.filter(
                price=bundle.data['price']).exists():
            tiers = ', '.join('"%s"' % p.price
                              for p in Price.objects.exclude(price="0.00"))
            raise fields.ApiFieldError(
                'Premium app specified without a valid price. Price can be'
                ' one of %s.' % (tiers,))
        else:
            ap.price = Price.objects.get(price=bundle.data['price'])
            ap.save()

    def dehydrate(self, bundle):
        obj = bundle.obj
        amo_user = getattr(bundle.request, 'amo_user', None)
        bundle.data.update(app_to_dict(obj,
            region=bundle.request.REGION.id, profile=amo_user))
        bundle.data['privacy_policy'] = (
            PrivacyPolicyResource().get_resource_uri(bundle))

        # Add extra data for reviewers. Used in reviewer tool search.
        bundle = update_with_reviewer_data(bundle)

        return bundle

    def hydrate_premium_type(self, bundle):
        typ = amo.ADDON_PREMIUM_API_LOOKUP.get(bundle.data['premium_type'],
                                               None)
        if typ is None:
            raise fields.ApiFieldError(
                "premium_type should be one of 'free', 'premium', 'free-inapp'"
                ", 'premium-inapp', or 'other'.")
        bundle.obj.premium_type = typ

    def get_object_list(self, request):
        if not request.amo_user:
            log.info('Anonymous listing not allowed')
            raise ImmediateHttpResponse(response=http.HttpForbidden())
        return self._meta.queryset.filter(type=amo.ADDON_WEBAPP,
                                          authors=request.amo_user)

    def override_urls(self):
        return [
            urls.url(
                r"^%s/(?P<pk>\d+)/(?P<resource_name>privacy)%s$" %
                    (self._meta.resource_name, trailing_slash()),
                self.wrap_view('get_privacy_policy'),
                name="api_dispatch_detail"),
            urls.url(
                r"^%s/(?P<app_slug>[^/<>\"']+)/"
                r"(?P<resource_name>privacy)%s$" %
                    (self._meta.resource_name, trailing_slash()),
                self.wrap_view('get_privacy_policy'),
                name="api_dispatch_detail"),
        ]

    def get_privacy_policy(self, request, **kwargs):
        return PrivacyPolicyResource().dispatch('detail', request, **kwargs)


class PrivacyPolicyResource(CORSResource, MarketplaceModelResource):

    class Meta(MarketplaceResource.Meta):
        api_name = 'apps'
        queryset = Webapp.objects.all()  # Gets overriden in dispatch.
        fields = ['privacy_policy']
        detail_allowed_methods = ['get', 'put']
        always_return_data = True
        authentication = OptionalOAuthAuthentication()
        authorization = AppOwnerAuthorization()
        resource_name = 'privacy'
        serializer = Serializer(formats=['json'])
        slug_lookup = 'app_slug'
        # Throttle users without Apps:APIUnthrottled at 10 POST requests/day.
        throttle = CacheThrottle(throttle_at=10, timeframe=60 * 60 * 24)


class StatusResource(MarketplaceModelResource):

    class Meta(MarketplaceModelResource.Meta):
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


class CategoryResource(CORSResource, MarketplaceModelResource):

    class Meta(MarketplaceModelResource.Meta):
        queryset = Category.objects.all()
        list_allowed_methods = ['get']
        allowed_methods = ['get']
        fields = ['name', 'id', 'slug']
        always_return_data = True
        resource_name = 'category'
        serializer = Serializer(formats=['json'])
        slug_lookup = 'slug'

    def dispatch(self, request_type, request, **kwargs):
        self._meta.queryset = Category.objects.filter(
            type=amo.ADDON_WEBAPP,
            weight__gte=0)
        return super(CategoryResource, self).dispatch(request_type, request,
                                                      **kwargs)

    def obj_get_list(self, request=None, **kwargs):
        objs = super(CategoryResource, self).obj_get_list(request, **kwargs)

        # Filter by region or worldwide.
        objs = objs.filter(Q(region__isnull=True) | Q(region=get_region_id()))

        # Check carrier.
        carrier = get_carrier_id()
        carrier_f = Q(carrier__isnull=True)
        if carrier:
            carrier_f |= Q(carrier=carrier)
        objs = objs.filter(carrier_f)

        return objs


class PreviewResource(CORSResource, MarketplaceModelResource):
    image_url = fields.CharField(attribute='image_url', readonly=True)
    thumbnail_url = fields.CharField(attribute='thumbnail_url', readonly=True)

    class Meta(MarketplaceModelResource.Meta):
        queryset = Preview.objects.all()
        list_allowed_methods = ['post']
        allowed_methods = ['get', 'delete']
        always_return_data = True
        fields = ['id', 'filetype', 'caption']
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


def waffles(request):
    switches = ['in-app-sandbox', 'allow-refund']
    flags = ['allow-b2g-paid-submission']
    res = dict([s, waffle.switch_is_active(s)] for s in switches)
    res.update(dict([f, waffle.flag_is_active(request, f)] for f in flags))
    return res


@memoize(prefix='config-settings')
def get_settings():
    safe = debug.get_safe_settings()
    _settings = ['SITE_URL']
    return dict([k, safe[k]] for k in _settings)


class ConfigResource(CORSResource, MarketplaceResource):
    """
    A resource that is designed to be exposed externally and contains
    settings or waffle flags that might be relevant to the client app.
    """
    version = fields.CharField()
    flags = fields.DictField('flags')
    settings = fields.DictField('settings')

    class Meta(MarketplaceResource.Meta):
        detail_allowed_methods = ['get']
        list_allowed_methods = []
        resource_name = 'config'

    def obj_get(self, request, **kw):
        if kw['pk'] != 'site':
            raise ImmediateHttpResponse(response=http.HttpNotFound())

        return GenericObject({
            # This is the git commit on IT servers.
            'version': getattr(settings, 'BUILD_ID_JS', ''),
            'flags': waffles(request),
            'settings': get_settings(),
        })


class RegionResource(CORSResource, MarketplaceResource):
    name = fields.CharField('name')
    slug = fields.CharField('slug')
    id = fields.IntegerField('id')
    default_currency = fields.CharField('default_currency')
    default_language = fields.CharField('default_language')
    has_payments = fields.BooleanField('has_payments')
    ratingsbodies = fields.ListField('ratingsbodies')

    class Meta(MarketplaceResource.Meta):
        detail_allowed_methods = ['get']
        list_allowed_methods = ['get']
        resource_name = 'region'
        slug_lookup = 'slug'

    def dehydrate_ratingsbodies(self, bundle):
        return [rb.name for rb in bundle.obj.ratingsbodies]

    def obj_get_list(self, request=None, **kwargs):
        return REGIONS_DICT.values()

    def obj_get(self, request=None, **kwargs):
        return REGIONS_DICT.get(kwargs['pk'], None)


class CarrierResource(CORSResource, MarketplaceResource):
    name = fields.CharField('name')
    slug = fields.CharField('slug')
    id = fields.IntegerField('id')

    class Meta(MarketplaceResource.Meta):
        detail_allowed_methods = ['get']
        list_allowed_methods = ['get']
        resource_name = 'carrier'
        slug_lookup = 'slug'

    def dehydrate_ratingsbodies(self, bundle):
        return [rb.name for rb in bundle.obj.ratingsbodies]

    def obj_get_list(self, request=None, **kwargs):
        return CARRIERS

    def obj_get(self, request=None, **kwargs):
        return CARRIER_MAP.get(kwargs['pk'], None)
