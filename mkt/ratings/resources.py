from django.conf.urls import url

import commonware.log
from tastypie import fields, http
from tastypie.bundle import Bundle
from tastypie.authorization import Authorization
from tastypie.utils import trailing_slash

import amo
from amo import get_user
from lib.metrics import record_action

from mkt.account.api import AccountResource
from mkt.api.authentication import (OptionalOAuthAuthentication,
                                    SharedSecretAuthentication)
from mkt.api.authorization import (AnonymousReadOnlyAuthorization,
                                   AppOwnerAuthorization,
                                   OwnerAuthorization,
                                   PermissionAuthorization)
from mkt.api.base import (CompatToOneField, CORSResource, http_error,
                          MarketplaceModelResource)
from mkt.api.resources import AppResource
from mkt.ratings.forms import ReviewForm
from mkt.regions import get_region, REGIONS_DICT
from mkt.webapps.models import Webapp
from reviews.models import Review, ReviewFlag

log = commonware.log.getLogger('z.api')


class RatingResource(CORSResource, MarketplaceModelResource):

    app = fields.ToOneField(AppResource, 'addon', readonly=True)
    user = fields.ToOneField(AccountResource, 'user', readonly=True, full=True)
    version = CompatToOneField(None, 'version', rest='version', readonly=True,
                               null=True, extra_fields=('version',))
    report_spam = fields.CharField()

    class Meta(MarketplaceModelResource.Meta):
        # Unfortunately, the model class name for ratings is "Review".
        queryset = Review.objects.valid()
        resource_name = 'rating'
        list_allowed_methods = ['get', 'post']
        detail_allowed_methods = ['get', 'put', 'delete']
        always_return_data = True
        authentication = (SharedSecretAuthentication(),
                          OptionalOAuthAuthentication())
        authorization = AnonymousReadOnlyAuthorization()
        fields = ['rating', 'body', 'modified', 'created']

        filtering = {
            'app': ('exact',),
            'user': ('exact',),
            'pk': ('exact',),
        }

        ordering = ['created']

    def dehydrate(self, bundle):
        bundle = super(RatingResource, self).dehydrate(bundle)
        if bundle.request.amo_user:
            amo_user = bundle.request.amo_user
            bundle.data['is_author'] = bundle.obj.user.pk == amo_user.pk
            bundle.data['has_flagged'] = (not bundle.data['is_author'] and
                bundle.obj.reviewflag_set.filter(user=amo_user).exists())
        return bundle

    def dehydrate_report_spam(self, bundle):
        return self._build_reverse_url(
            'api_post_flag',
            kwargs={'api_name': self._meta.api_name,
                    'resource_name': self._meta.resource_name,
                    'review_id': bundle.obj.pk})

    def _review_data(self, request, app, form):
        data = dict(addon_id=app.id, user_id=request.user.id,
                    ip_address=request.META.get('REMOTE_ADDR', ''))
        if app.is_packaged:
            data['version_id'] = app.current_version.id
        data.update(**form.cleaned_data)
        return data

    def get_app(self, ident):
        try:
            app = Webapp.objects.valid().get(id=ident)
        except (Webapp.DoesNotExist, ValueError):
            try:
                app = Webapp.objects.valid().get(app_slug=ident)
            except Webapp.DoesNotExist:
                raise self.non_form_errors([('app', 'Invalid app')])
        if not app.listed_in(region=REGIONS_DICT[get_region()]):
            raise self.non_form_errors([('app', 'Not available in this region')])
        return app

    def build_filters(self, filters=None):
        """
        If `addon__exact` is a filter and its value cannot be coerced into an
        int, assume that it's a slug lookup.

        Run the query necessary to determine the app, and substitute the slug
        with the PK in the filter so tastypie will continue doing its thing.
        """
        built = super(RatingResource, self).build_filters(filters)
        if 'addon__exact' in built:
            try:
                int(built['addon__exact'])
            except ValueError:
                app = self.get_app(built['addon__exact'])
                if app:
                    built['addon__exact'] = str(app.pk)

        if built.get('user__exact', None) == 'mine':
            # This is a cheat. Would prefer /mine/ in the URL.
            user = get_user()
            if not user:
                # You must be logged in to use "mine".
                raise http_error(http.HttpUnauthorized, 'You must be logged in to access "mine".')

            built['user__exact'] = user.pk
        return built

    def obj_create(self, bundle, request=None, **kwargs):
        """
        Handle POST requests to the resource. If the data validates, create a
        new Review from bundle data.
        """
        form = ReviewForm(bundle.data)

        if not form.is_valid():
            raise self.form_errors(form)

        app = self.get_app(bundle.data['app'])

        # Return 409 if the user has already reviewed this app.
        qs = self._meta.queryset.filter(addon=app, user=request.user)
        if app.is_packaged:
            qs = qs.filter(version_id=app.current_version.id)
        if qs.exists():
            raise http_error(http.HttpConflict, 'You have already reviewed this app.')

        # Return 403 if the user is attempting to review their own app:
        if app.has_author(request.user):
            raise http_error(http.HttpForbidden, 'You may not review your own app.')

        # Return 403 if not a free app and the user hasn't purchased it.
        if app.is_premium() and not app.is_purchased(request.amo_user):
            raise http_error(
                http.HttpForbidden,
                "You may not review paid apps you haven't purchased.")

        bundle.obj = Review.objects.create(**self._review_data(request, app,
                                                               form))

        amo.log(amo.LOG.ADD_REVIEW, app, bundle.obj)
        log.debug('[Review:%s] Created by user %s ' %
                  (bundle.obj.id, request.user.id))
        record_action('new-review', request, {'app-id': app.id})

        return bundle

    def obj_update(self, bundle, request, **kwargs):
        """
        Handle PUT requests to the resource. If authorized and the data
        validates, update the indicated resource with bundle data.
        """
        form = ReviewForm(bundle.data)
        if not form.is_valid():
            raise self.form_errors(form)

        if 'app' in bundle.data:
            error = ('app', "Cannot update a rating's `app`")
            raise self.non_form_errors([error])

        sup = super(RatingResource, self).obj_update(bundle, request, **kwargs)

        amo.log(amo.LOG.EDIT_REVIEW, bundle.obj.addon, bundle.obj)
        log.debug('[Review:%s] Edited by %s' % (bundle.obj.id, request.user.id))

        return sup

    def obj_delete(self, request, **kwargs):
        obj = self.get_by_resource_or_404(request, **kwargs)
        if not (AppOwnerAuthorization().is_authorized(request,
                                                      object=obj.addon)
                or OwnerAuthorization().is_authorized(request, object=obj)
                or PermissionAuthorization('Users',
                                           'Edit').is_authorized(request)
                or PermissionAuthorization('Addons',
                                           'Edit').is_authorized(request)):
            raise http_error(
                http.HttpForbidden,
                'You do not have permission to delete this review.')

        log.info('Rating %s deleted from addon %s' % (obj.pk, obj.addon.pk))
        return super(RatingResource, self).obj_delete(request, **kwargs)

    def get_object_list(self, request):
        qs = MarketplaceModelResource.get_object_list(self, request)
        # Mature regions show only reviews from within that region.
        if not request.REGION.adolescent:
            qs = qs.filter(client_data__region=request.REGION.id)
        return qs

    def alter_list_data_to_serialize(self, request, data):
        if 'app' in request.GET:
            addon = self.get_app(request.GET['app'])
            data['info'] = {
                'average': addon.average_rating,
                'slug': addon.app_slug,
                'current_version': addon.current_version.version
            }

            filters = dict(addon=addon)
            if addon.is_packaged:
                filters['version'] = addon.current_version

            if not request.user.is_anonymous():
                filters['user'] = request.user
                existing_review = Review.objects.valid().filter(**filters)
                if addon.is_premium():
                    can_rate = addon.has_purchased(request.amo_user)
                else:
                    can_rate = not addon.has_author(request.user)
                data['user'] = {'can_rate': can_rate,
                                'has_rated': existing_review.exists()}
            else:
                data['user'] = None

        return data

    def override_urls(self):
        # Based on 'nested resource' example in tastypie cookbook.
        return [
            url(r'^(?P<resource_name>%s)/(?P<review_id>\w[\w/-]*)/flag%s$' %
                (self._meta.resource_name, trailing_slash()),
                self.wrap_view('post_flag'), name='api_post_flag')
        ]

    def post_flag(self, request, **kwargs):
        return RatingFlagResource().dispatch('list', request,
                                             review_id=kwargs['review_id'])


class FireplaceRatingResource(RatingResource):
    class Meta(RatingResource.Meta):
        pass


class RatingFlagResource(CORSResource, MarketplaceModelResource):

    class Meta(MarketplaceModelResource.Meta):
        queryset = ReviewFlag.objects.all()
        resource_name = 'rating_flag'
        list_allowed_methods = ['post']
        detail_allowed_methods = []
        authentication = (SharedSecretAuthentication(),
                          OptionalOAuthAuthentication())
        authorization = Authorization()
        fields = ['review', 'flag', 'note', 'user']

    def get_resource_uri(self, bundle_or_obj):
        if isinstance(bundle_or_obj, Bundle):
            obj = bundle_or_obj.obj
        else:
            obj = bundle_or_obj

        return '/api/apps/ratings/%s/flag/%s%s' % (obj.review_id, obj.pk,
                                                   trailing_slash())

    def post_list(self, request, review_id=None, **kwargs):
        if ReviewFlag.objects.filter(review_id=review_id,
                                     user=request.amo_user).exists():
            return http.HttpConflict()
        return MarketplaceModelResource.post_list(
            self, request, review_id=review_id, **kwargs)

    def obj_create(self, bundle, request=None, review_id=None, **kwargs):
        if 'note' in bundle.data and bundle.data['note'].strip():
            bundle.data['flag'] = ReviewFlag.OTHER
        Review.objects.filter(id=review_id).update(editorreview=True)
        return MarketplaceModelResource.obj_create(
            self, bundle, request=request, review_id=review_id,
            user=request.amo_user)
