from django.conf import settings, urls
from django.db import transaction
from django.db.models import Q
from django.views import debug

import commonware.log
import waffle
from celery_tasktree import TaskTree
import raven.base
from rest_framework.decorators import api_view, permission_classes
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.serializers import (ModelSerializer, CharField,
                                        HyperlinkedIdentityField)

from tastypie import fields, http
from tastypie.serializers import Serializer
from tastypie.throttle import CacheThrottle
from tastypie.utils import trailing_slash

import amo
from amo.utils import memoize
from addons.forms import CategoryFormSet
from addons.models import Addon, AddonUser, Category, Webapp
from amo.decorators import write
from amo.utils import no_translation
from constants.applications import DEVICE_TYPES
from files.models import Platform
from lib.metrics import record_action
from market.models import AddonPremium, Price

from mkt.api.authentication import (SharedSecretAuthentication,
                                    OptionalOAuthAuthentication)
from mkt.api.authorization import AppOwnerAuthorization, OwnerAuthorization
from mkt.api.base import (CORSResource, CORSViewSet, GenericObject,
                          http_error, MarketplaceModelResource,
                          MarketplaceResource)
from mkt.api.forms import (CategoryForm, DeviceTypeForm, UploadForm)
from mkt.api.http import HttpLegallyUnavailable
from mkt.carriers import CARRIER_MAP, CARRIERS, get_carrier_id
from mkt.developers import tasks
from mkt.regions import get_region, get_region_id, REGIONS_DICT
from mkt.submit.forms import AppDetailsBasicForm
from mkt.webapps.models import get_excluded_in
from mkt.webapps.utils import app_to_dict, update_with_reviewer_data

log = commonware.log.getLogger('z.api')


class AppResource(CORSResource, MarketplaceModelResource):
    payment_account = fields.ToOneField('mkt.developers.api.AccountResource',
                                        'app_payment_account', null=True)
    premium_type = fields.IntegerField(null=True)
    previews = fields.ToManyField('mkt.submit.api.PreviewResource',
                                  'previews', readonly=True)
    upsold = fields.ToOneField('mkt.api.resources.AppResource', 'upsold',
                               null=True)

    class Meta(MarketplaceModelResource.Meta):
        queryset = Webapp.objects.all()  # Gets overriden in dispatch.
        fields = ['categories', 'description', 'device_types', 'homepage',
                  'id', 'name', 'payment_account', 'premium_type',
                  'status', 'support_email', 'support_url']
        list_allowed_methods = ['get', 'post']
        detail_allowed_methods = ['get', 'put', 'delete']
        always_return_data = True
        authentication = (SharedSecretAuthentication(),
                          OptionalOAuthAuthentication())
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
            raise http_error(http.HttpUnauthorized,
                             'Terms of service not accepted.')

        if not form.is_valid():
            raise self.form_errors(form)

        if not (OwnerAuthorization()
                .is_authorized(request, object=form.obj)):
            raise http_error(http.HttpForbidden,
                             'You do not own that app.')

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
            unavail = self._meta.queryset_base.filter(**kwargs)
            if unavail.exists():
                obj = unavail[0]
                # Owners can see their app no matter what region.
                if AppOwnerAuthorization().is_authorized(request, object=obj):
                    return obj
                raise http_error(HttpLegallyUnavailable,
                                 'Not available in your region.')
            raise http_error(http.HttpNotFound,
                             'No such app.')

        # If it's public, just return it.
        if allow_anon and obj.is_public():
            return obj

        # Now do the final check to see if you are allowed to see it and
        # return a 403 if you can't.
        if not AppOwnerAuthorization().is_authorized(request, object=obj):
            raise http_error(http.HttpForbidden,
                             'You do not own that app.')
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
        bundle = update_with_reviewer_data(bundle, using_es=False)

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
            raise http_error(http.HttpForbidden,
                             'Anonymous listing not allowed.')
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


class CategorySerializer(ModelSerializer):
    name = CharField('name')
    resource_uri = HyperlinkedIdentityField(view_name='app-category-detail')

    class Meta:
        model = Category
        fields = ('name', 'id', 'resource_uri', 'slug')
        view_name = 'category'


class CategoryViewSet(ListModelMixin, RetrieveModelMixin, CORSViewSet):
    model = Category
    serializer_class = CategorySerializer
    permission_classes = (AllowAny,)
    cors_allowed_methods = ('get',)
    slug_lookup = 'slug'

    def get_queryset(self):
        qs = Category.objects.filter(type=amo.ADDON_WEBAPP,
                                     weight__gte=0)
        if self.action == 'list':
            qs = qs.filter(Q(region__isnull=True) |
                           Q(region=get_region_id()))
            # Check carrier.
            carrier = get_carrier_id()
            carrier_f = Q(carrier__isnull=True)
            if carrier:
                carrier_f |= Q(carrier=carrier)
            qs = qs.filter(carrier_f)
        return qs


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
            raise http_error(http.HttpNotFound,
                             'No such configuration.')

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


@api_view(['POST'])
@permission_classes([AllowAny])
def error_reporter(request):
    request._request.CORS = ['POST']
    client = raven.base.Client(settings.SENTRY_DSN)
    client.capture('raven.events.Exception', data=request.DATA)
    return Response(status=204)
