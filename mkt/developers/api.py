import json

from django.http import Http404

import commonware
from curling.lib import HttpClientError, HttpServerError
from tastypie import http
from tastypie.authorization import Authorization
from tastypie.exceptions import ImmediateHttpResponse, NotFound
from tower import ugettext as _

from rest_framework import status
from rest_framework.generics import CreateAPIView, ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.serializers import ModelSerializer, SerializerMethodField

import lib.iarc
from mkt.api.authentication import OAuthAuthentication
from mkt.api.base import CORSMixin, MarketplaceModelResource, SlugOrIdMixin
from mkt.developers.forms import ContentRatingForm
from mkt.developers.forms_payments import BangoPaymentAccountForm
from mkt.developers.models import CantCancel, PaymentAccount
from mkt.webapps.models import ContentRating, Webapp


log = commonware.log.getLogger('z.devhub')


class BangoFormValidation(object):

    def is_valid(self, bundle, request=None):
        data = bundle.data or {}
        if request.method == 'PUT':
            form = BangoPaymentAccountForm(data, account=True)
        else:
            form = BangoPaymentAccountForm(data)
        if form.is_valid():
            return {}
        return form.errors


class AccountResource(MarketplaceModelResource):

    class Meta(MarketplaceModelResource.Meta):
        validation = BangoFormValidation()
        queryset = PaymentAccount.objects.all()
        list_allowed_methods = ['get', 'post']
        detail_allowed_methods = ['get', 'put', 'delete']
        authentication = OAuthAuthentication()
        authorization = Authorization()
        resource_name = 'account'

    def get_object_list(self, request):
        qs = MarketplaceModelResource.get_object_list(self, request)
        return qs.filter(user=request.amo_user, inactive=False)

    def obj_create(self, bundle, request=None, **kwargs):
        try:
            bundle.obj = PaymentAccount.create_bango(
                request.amo_user, bundle.data)
        except HttpClientError as e:
            log.error('Client error create Bango account; %s' % e)
            raise ImmediateHttpResponse(
                http.HttpApplicationError(json.dumps(e.content)))
        except HttpServerError as e:
            log.error('Error creating Bango payment account; %s' % e)
            raise ImmediateHttpResponse(http.HttpApplicationError(
                _(u'Could not connect to payment server.')))
        return bundle

    def obj_update(self, bundle, request=None, **kwargs):
        bundle.obj = self.obj_get(request, **kwargs)
        bundle.obj.update_account_details(**bundle.data)
        return bundle

    def full_dehydrate(self, bundle):
        bundle.data = bundle.obj.get_details()
        bundle.data['resource_uri'] = self.get_resource_uri(bundle)
        return bundle

    def obj_delete(self, request=None, **kwargs):
        try:
            account = self.obj_get(request, **kwargs)
        except PaymentAccount.DoesNotExist:
            raise NotFound('A model instance matching the provided arguments '
                           'could not be found.')
        try:
            account.cancel(disable_refs=True)
        except CantCancel:
            raise ImmediateHttpResponse(http.HttpConflict(
                _('Cannot delete shared account')))
        log.info('Account cancelled: %s' % account.pk)


class ContentRatingSerializer(ModelSerializer):
    body_name = SerializerMethodField('get_body_name')
    body_slug = SerializerMethodField('get_body_slug')

    name = SerializerMethodField('get_rating_name')
    slug = SerializerMethodField('get_rating_slug')
    description = SerializerMethodField('get_rating_description')

    def get_body_name(self, obj):
        return obj.get_body().name

    def get_body_slug(self, obj):
        return obj.get_body().slug

    def get_rating_name(self, obj):
        return obj.get_rating().name

    def get_rating_slug(self, obj):
        return obj.get_rating().slug

    def get_rating_description(self, obj):
        return obj.get_rating().description

    class Meta:
        model = ContentRating
        fields = ('id', 'created', 'modified', 'body_name', 'body_slug',
                  'name', 'slug', 'description')


class ContentRatingList(CORSMixin, SlugOrIdMixin, ListAPIView):
    model = ContentRating
    serializer_class = ContentRatingSerializer
    permission_classes = (AllowAny,)
    cors_allowed_methods = ['get']

    queryset = Webapp.objects.all()
    slug_field = 'app_slug'

    def get(self, request, *args, **kwargs):
        app = self.get_object()

        self.queryset = app.content_ratings.all()

        if 'since' in request.GET:
            form = ContentRatingForm(request.GET)
            if form.is_valid():
                self.queryset = self.queryset.filter(
                    modified__gt=form.cleaned_data['since'])

        if not self.queryset.exists():
            raise Http404()

        return super(ContentRatingList, self).get(self, request)


class ContentRatingsPingback(CORSMixin, SlugOrIdMixin, CreateAPIView):
    cors_allowed_methods = ['post']
    parser_classes = (lib.iarc.utils.IARC_JSON_Parser,)
    permission_classes = (AllowAny,)

    queryset = Webapp.objects.all()
    slug_field = 'app_slug'

    def post(self, request, pk, *args, **kwargs):
        app = self.get_object()

        # Verify token.
        data = request.DATA[0]
        if app.iarc_token() != data.get('token'):
            return Response({'detail': 'Token mismatch'},
                            status=status.HTTP_400_BAD_REQUEST)

        if data.get('ratings'):
            # We found a rating, so store the id and code for future use.
            if 'submission_id' in data and 'security_code' in data:
                app.set_iarc_info(data['submission_id'], data['security_code'])

            app.set_content_ratings(data.get('ratings', {}))
            app.set_descriptors(data.get('descriptors', []))
            app.set_interactives(data.get('interactives', []))

        return Response('ok')
