import json
from decimal import Decimal

from django import forms as django_forms
from django.core.urlresolvers import reverse
from django.http import Http404

import commonware
from rest_framework import (exceptions, permissions, response, serializers,
                            status, viewsets)
from rest_framework.decorators import action
from rest_framework.response import Response
from tower import ungettext as ngettext

import amo
from addons.models import (AddonCategory, AddonUpsell, AddonUser, Category,
                           Preview)
from amo.utils import no_translation
from files.models import FileUpload, Platform
from lib.metrics import record_action
from market.models import AddonPremium, Price

from mkt.api.authentication import (RestAnonymousAuthentication,
                                    RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.authorization import AllowAppOwner, AllowReviewerReadOnly, AnyOf
from mkt.api.base import CORSMixin, get_url, SlugOrIdMixin
from mkt.api.exceptions import HttpLegallyUnavailable
from mkt.api.fields import (LargeTextField, ReverseChoiceField,
                            TranslationSerializerField)
from mkt.constants.features import FeatureProfile
from mkt.developers import tasks
from mkt.developers.forms import IARCGetAppInfoForm
from mkt.purchase.utils import payments_enabled
from mkt.regions import (ALL_REGIONS_WITH_CONTENT_RATINGS, get_region,
                         REGIONS_DICT)
from mkt.submit.forms import mark_for_rereview
from mkt.webapps.models import (AddonExcludedRegion, AppFeatures,
                                get_excluded_in, reverse_version, Webapp)


log = commonware.log.getLogger('z.api')


class AppFeaturesSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppFeatures

    def to_native(self, obj):
        ret = super(AppFeaturesSerializer, self).to_native(obj)
        profile = FeatureProfile.from_signature(obj.to_signature())
        ret['required'] = profile.to_list()
        return ret


def http_error(errorclass, reason, extra_data=None):
    r = errorclass()
    data = {'reason': reason}
    if extra_data:
        data.update(extra_data)
    r.content = json.dumps(data)
    return response.Response(r)


class PreviewSerializer(serializers.ModelSerializer):
    filetype = serializers.CharField()
    id = serializers.IntegerField(source='pk')
    image_url = serializers.CharField()
    resource_uri = serializers.SerializerMethodField('get_resource_uri')
    thumbnail_url = serializers.CharField()

    class Meta:
        model = Preview
        fields = ['filetype', 'image_url', 'id', 'resource_uri',
                  'thumbnail_url']

    def get_resource_uri(self, request):
        if self.object is None:
            return None
        return get_url('preview', pk=self.object.pk)


class RegionSerializer(serializers.Serializer):
    name = serializers.CharField()
    slug = serializers.CharField()
    mcc = serializers.CharField()
    adolescent = serializers.BooleanField()


class SemiSerializerMethodField(serializers.SerializerMethodField):
    """
    Used for fields serialized with a method on the serializer but who
    need to handle unserialization manually.
    """
    def field_from_native(self, data, files, field_name, into):
        into[field_name] = data.get(field_name, None)


class AppSerializer(serializers.ModelSerializer):

    app_type = serializers.ChoiceField(
        choices=amo.ADDON_WEBAPP_TYPES_LOOKUP.items(), read_only=True)
    author = serializers.CharField(source='developer_name', read_only=True)
    categories = serializers.SlugRelatedField(
        many=True, slug_field='slug', required=True,
        queryset=Category.objects.filter(type=amo.ADDON_WEBAPP))
    content_ratings = serializers.SerializerMethodField('get_content_ratings')
    created = serializers.DateField(read_only=True)
    current_version = serializers.CharField(
        source='current_version.version',
        read_only=True)
    default_locale = serializers.CharField(read_only=True)
    device_types = SemiSerializerMethodField('get_device_types')
    description = TranslationSerializerField(required=False)
    homepage = TranslationSerializerField(required=False)
    icons = serializers.SerializerMethodField('get_icons')
    id = serializers.IntegerField(source='pk', required=False)
    is_packaged = serializers.BooleanField(read_only=True)
    manifest_url = serializers.CharField(source='get_manifest_url',
                                         read_only=True)
    name = TranslationSerializerField(required=False)
    payment_account = serializers.HyperlinkedRelatedField(
        view_name='payment-account-detail', source='app_payment_account',
        required=False)
    payment_required = serializers.SerializerMethodField(
        'get_payment_required')
    premium_type = ReverseChoiceField(
        choices_dict=amo.ADDON_PREMIUM_API, required=False)
    previews = PreviewSerializer(many=True, required=False)
    price = SemiSerializerMethodField('get_price')
    price_locale = serializers.SerializerMethodField('get_price_locale')
    privacy_policy = LargeTextField(view_name='app-privacy-policy-detail',
                                    required=False)
    public_stats = serializers.BooleanField(read_only=True)
    ratings = serializers.SerializerMethodField('get_ratings_aggregates')
    regions = RegionSerializer(read_only=True, source='get_regions')
    resource_uri = serializers.HyperlinkedIdentityField(view_name='app-detail')
    slug = serializers.CharField(source='app_slug', required=False)
    status = serializers.IntegerField(read_only=True)
    summary = TranslationSerializerField(required=False)
    support_email = TranslationSerializerField(required=False)

    support_url = TranslationSerializerField(required=False)
    supported_locales = serializers.SerializerMethodField(
        'get_supported_locales')
    tags = serializers.SerializerMethodField('get_tags')
    upsell = serializers.SerializerMethodField('get_upsell')
    upsold = serializers.HyperlinkedRelatedField(
        view_name='app-detail', source='upsold.free',
        required=False, queryset=Webapp.objects.all())
    user = serializers.SerializerMethodField('get_user_info')
    versions = serializers.SerializerMethodField('get_versions')
    weekly_downloads = serializers.SerializerMethodField(
        'get_weekly_downloads')

    class Meta:
        model = Webapp
        exclude = ['_latest_version', 'ts_slowness', '_backup_version',
                   'last_updated', 'nomination_message', '_current_version',
                   'make_public', 'charity', 'modified']

    def get_content_ratings(self, app):
        return {
            'ratings': app.get_content_ratings_by_region() or None,
            'descriptors': app.get_descriptors() or None,
            'interactive_elements': app.get_interactives() or None,
        }

    def get_icons(self, app):
        return dict([(icon_size, app.get_icon_url(icon_size))
                     for icon_size in (16, 48, 64, 128)])

    def get_payment_required(self, app):
        if app.premium:
            tier = app.get_tier()
            return bool(tier and tier.price)
        return False

    def get_price(self, app):
        region = self.context.get('region')
        if (region in app.get_price_region_ids() or
            payments_enabled(self.context['request'])):
            return app.get_price(region=region)

    def get_price_locale(self, app):
        region = self.context.get('region')
        if (region in app.get_price_region_ids() or
            payments_enabled(self.context['request'])):
            return app.get_price_locale(region=region)

    def get_ratings_aggregates(self, app):
        return {'average': app.average_rating,
                'count': app.total_reviews}

    def get_supported_locales(self, app):
        locs = getattr(app.current_version, 'supported_locales', '')
        if locs:
            return locs.split(',')
        else:
            return []

    def get_tags(self, app):
        return [t.tag_text for t in app.tags.all()]

    def get_upsell(self, app):
        if (app.upsell and self.context.get('region') in
                app.upsell.premium.get_price_region_ids()):
            upsell = app.upsell.premium
            return {
                'id': upsell.id,
                'app_slug': upsell.app_slug,
                'icon_url': upsell.get_icon_url(128),
                'name': unicode(upsell.name),
                'resource_uri': reverse('app-detail', kwargs={'pk': upsell.pk})
            }
        else:
            return False

    def get_user_info(self, app):
        user = self.context.get('profile')
        if user:
            return {
                'developed': app.addonuser_set.filter(
                    user=user, role=amo.AUTHOR_ROLE_OWNER).exists(),
                'installed': app.has_installed(user),
                'purchased': app.pk in user.purchase_ids(),
            }

    def get_versions(self, app):
        return dict((v.version, reverse_version(v)) for
                    v in app.versions.all())

    def get_weekly_downloads(self, app):
        if app.public_stats:
            return app.weekly_downloads

    def validate_categories(self, attrs, source):
        if not attrs.get('categories'):
            raise serializers.ValidationError('This field is required.')
        set_categories = set(attrs[source])
        total = len(set_categories)
        max_cat = amo.MAX_CATEGORIES

        if total > max_cat:
            # L10n: {0} is the number of categories.
            raise serializers.ValidationError(ngettext(
                'You can have only {0} category.',
                'You can have only {0} categories.',
                max_cat).format(max_cat))
        return attrs

    def get_device_types(self, app):
        with no_translation():
            return [n.api_name for n in app.device_types]

    def save_device_types(self, obj, new_types):
        new_types = [amo.DEVICE_LOOKUP[d].id for d in new_types]
        old_types = [x.id for x in obj.device_types]

        added_devices = set(new_types) - set(old_types)
        removed_devices = set(old_types) - set(new_types)

        for d in added_devices:
            obj.addondevicetype_set.create(device_type=d)
        for d in removed_devices:
            obj.addondevicetype_set.filter(device_type=d).delete()

        # Send app to re-review queue if public and new devices are added.
        if added_devices and obj.status in amo.WEBAPPS_APPROVED_STATUSES:
            mark_for_rereview(obj, added_devices, removed_devices)

    def save_categories(self, obj, categories):
        before = set(obj.categories.values_list('id', flat=True))
        # Add new categories.
        to_add = set(c.id for c in categories) - before
        for c in to_add:
            AddonCategory.objects.create(addon=obj, category_id=c)

        # Remove old categories.
        to_remove = before - set(categories)
        for c in to_remove:
            obj.addoncategory_set.filter(category=c).delete()

        # Disallow games in Brazil without a rating.
        games = Webapp.category('games')
        if not games:
            return

        for region in ALL_REGIONS_WITH_CONTENT_RATINGS:
            if (self.product.listed_in(region) and
                not self.product.content_ratings_in(region)):

                if games.id in to_add:
                    aer, created = AddonExcludedRegion.objects.get_or_create(
                        addon=self.product, region=region.id)
                    if created:
                        log.info(u'[Webapp:%s] Game excluded from new region '
                                 u'(%s).' % (self.product, region.slug))

                elif games.id in to_remove:
                    self.product.addonexcludedregion.filter(
                        region=region.id).delete()
                    log.info(u'[Webapp:%s] Game no longer excluded from region'
                             u' (%s).' % (self.product, region.slug))

    def save_upsold(self, obj, upsold):
        current_upsell = obj.upsold
        if upsold and upsold != obj.upsold.free:
            if not current_upsell:
                log.debug('[1@%s] Creating app upsell' % obj.pk)
                current_upsell = AddonUpsell(premium=obj)
            current_upsell.free = upsold
            current_upsell.save()

        elif current_upsell:
            # We're deleting the upsell.
            log.debug('[1@%s] Deleting the app upsell' % obj.pk)
            current_upsell.delete()

    def save_price(self, obj, price):
        premium = obj.premium
        if not premium:
            premium = AddonPremium()
            premium.addon = obj
        premium.price = Price.objects.active().get(price=price)
        premium.save()

    def validate_device_types(self, attrs, source):
        if attrs.get('device_types') is None:
            raise serializers.ValidationError('This field is required.')
        for v in attrs['device_types']:
            if v not in amo.DEVICE_LOOKUP.keys():
                raise serializers.ValidationError(
                    str(v) + ' is not one of the available choices.')
        return attrs

    def validate_price(self, attrs, source):
        if attrs.get('premium_type', None) not in (amo.ADDON_FREE,
                                                   amo.ADDON_FREE_INAPP):
            valid_prices = Price.objects.exclude(
                price='0.00').values_list('price', flat=True)
            price = attrs.get('price')
            if not (price and Decimal(price) in valid_prices):
                raise serializers.ValidationError(
                    'Premium app specified without a valid price. Price can be'
                    ' one of %s.' % (', '.join('"%s"' % str(p)
                                               for p in valid_prices),))
        return attrs

    def restore_object(self, attrs, instance=None):
        # restore_object creates or updates a model instance, during
        # input validation.
        extras = []
        # Upsell bits are handled here because we need to remove it
        # from the attrs dict before deserializing.
        upsold = attrs.pop('upsold.free', None)
        if upsold is not None:
            extras.append((self.save_upsold, upsold))
        price = attrs.pop('price', None)
        if price is not None:
            extras.append((self.save_price, price))
        device_types = attrs['device_types']
        if device_types:
            extras.append((self.save_device_types, device_types))
            del attrs['device_types']
        if attrs.get('app_payment_account') is None:
            attrs.pop('app_payment_account')
        instance = super(AppSerializer, self).restore_object(
            attrs, instance=instance)
        for f, v in extras:
            f(instance, v)
        return instance

    def save_object(self, obj, **kwargs):
        # this only gets called if validation succeeds.
        m2m = getattr(obj, '_m2m_data', {})
        cats = m2m.pop('categories', None)
        super(AppSerializer, self).save_object(obj, **kwargs)
        # Categories are handled here because we can't look up
        # existing ones until the initial save is done.
        self.save_categories(obj, cats)


class PublicAppReadOnly(permissions.BasePermission):
    """
    The request does not modify the webapp, and it's publically available.
    """
    def has_permission(self, request, view):
        return request.method in permissions.SAFE_METHODS

    def has_object_permission(self, request, view, object):
        return object.is_public() and request.method in permissions.SAFE_METHODS


class AppViewSet(CORSMixin, SlugOrIdMixin, viewsets.ModelViewSet):
    serializer_class = AppSerializer
    slug_field = 'app_slug'
    cors_allowed_methods = ('get', 'put', 'post', 'delete')
    permission_classes = [AnyOf(AllowAppOwner, AllowReviewerReadOnly,
                                PublicAppReadOnly)]
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]

    def get_serializer_context(self):
        ctx = super(AppViewSet, self).get_serializer_context()
        ctx['profile'] = getattr(self.request, 'amo_user', None)
        ctx['region'] = (self.request.REGION.id
                         if hasattr(self.request, 'REGION')
                         else None)
        return ctx

    def get_queryset(self):
        return Webapp.objects.all().exclude(
            id__in=get_excluded_in(REGIONS_DICT[get_region()].id))

    def get_base_queryset(self):
        return Webapp.objects.all()

    def get_object(self, queryset=None):
        try:
            app = super(AppViewSet, self).get_object()
        except Http404:
            app = super(AppViewSet, self).get_object(self.get_base_queryset())
            # Owners and reviewers can see apps regardless of region.
            owner_or_reviewer = AnyOf(AllowAppOwner, AllowReviewerReadOnly)
            if owner_or_reviewer.has_object_permission(self.request, self, app):
                return app
            data = {}
            for key in ('name', 'support_email', 'support_url'):
                value = getattr(app, key)
                data[key] = unicode(value) if value else ''
            data['reason'] = 'Not available in your region.'
            raise HttpLegallyUnavailable(data)
        self.check_object_permissions(self.request, app)
        return app

    def create(self, request, *args, **kwargs):
        uuid = request.DATA.get('upload', '')
        if uuid:
            is_packaged = True
        else:
            uuid = request.DATA.get('manifest', '')
            is_packaged = False
        if not uuid:
            raise serializers.ValidationError('No upload or manifest specified.')

        try:
            upload = FileUpload.objects.get(uuid=uuid)
        except FileUpload.DoesNotExist:
            raise exceptions.ParseError('No upload found.')
        if not upload.valid:
            raise exceptions.ParseError('Upload not valid.')

        if not request.amo_user.read_dev_agreement:
            log.info(u'Attempt to use API without dev agreement: %s'
                     % request.amo_user.pk)
            raise exceptions.PermissionDenied('Terms of Service not accepted.')
        if not (upload.user and upload.user.pk == request.amo_user.pk):
            raise exceptions.PermissionDenied('You do not own that app.')
        plats = [Platform.objects.get(id=amo.PLATFORM_ALL.id)]

        # Create app, user and fetch the icon.
        obj = Webapp.from_upload(upload, plats, is_packaged=is_packaged)
        AddonUser(addon=obj, user=request.amo_user).save()
        tasks.fetch_icon.delay(obj)
        record_action('app-submitted', request, {'app-id': obj.pk})

        log.info('App created: %s' % obj.pk)
        data = AppSerializer(
            context=self.get_serializer_context()).to_native(obj)

        return response.Response(
            data, status=201,
            headers={'Location': reverse('app-detail', kwargs={'pk': obj.pk})})

    def update(self, request, *args, **kwargs):
        # Fail if the app doesn't exist yet.
        self.get_object()
        r = super(AppViewSet, self).update(request, *args, **kwargs)
        # Be compatible with tastypie responses.
        if r.status_code == 200:
            r.status_code = 202
        return r

    def list(self, request, *args, **kwargs):
        if not request.amo_user:
            log.info('Anonymous listing not allowed')
            raise exceptions.PermissionDenied('Anonymous listing not allowed.')

        self.object_list = self.filter_queryset(self.get_queryset().filter(
            authors=request.amo_user))
        page = self.paginate_queryset(self.object_list)
        serializer = self.get_pagination_serializer(page)
        return response.Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        raise exceptions.MethodNotAllowed('PATCH')

    @action()
    def content_ratings(self, request, *args, **kwargs):
        app = self.get_object()
        form = IARCGetAppInfoForm(data=request.DATA)

        if form.is_valid():
            try:
                form.save(app)
                return Response(status=status.HTTP_204_NO_CONTENT)
            except django_forms.ValidationError:
                pass

        return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)


class PrivacyPolicyViewSet(CORSMixin, SlugOrIdMixin, viewsets.GenericViewSet):
    queryset = Webapp.objects.all()
    cors_allowed_methods = ('get',)
    permission_classes = [AnyOf(AllowAppOwner, PublicAppReadOnly)]
    slug_field = 'app_slug'
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]

    def retrieve(self, request, *args, **kwargs):
        app = self.get_object()
        return response.Response({'privacy_policy': unicode(app.privacy_policy)},
                                 content_type='application/json')
