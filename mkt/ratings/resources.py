from django.conf.urls import url

import commonware.log
from tastypie import fields, http
from tastypie.bundle import Bundle
from tastypie.authorization import Authorization
from tastypie.exceptions import ImmediateHttpResponse
from tastypie.utils import trailing_slash

import amo
from addons.models import Addon
from lib.metrics import record_action

from mkt.api.authentication import (AppOwnerAuthorization,
                                    OAuthAuthentication,
                                    OptionalOAuthAuthentication,
                                    OwnerAuthorization,
                                    PermissionAuthorization,
                                    SharedSecretAuthentication)
from mkt.api.authorization import AnonymousReadOnlyAuthorization
from mkt.api.base import MarketplaceModelResource
from mkt.api.resources import AppResource, UserResource
from mkt.ratings.forms import ReviewForm
from mkt.webapps.models import Webapp
from reviews.models import Review, ReviewFlag

log = commonware.log.getLogger('z.api')


class RatingResource(MarketplaceModelResource):

    app = fields.ToOneField(AppResource, 'addon', readonly=True)
    user = fields.ToOneField(UserResource, 'user', readonly=True, full=True)
    report_spam = fields.CharField()

    class Meta:
        # Unfortunately, the model class name for ratings is "Review".
        queryset = Review.objects.valid()
        resource_name = 'rating'
        list_allowed_methods = ['get', 'post']
        detail_allowed_methods = ['get', 'put', 'delete']
        always_return_data = True
        authentication = (SharedSecretAuthentication(),
                          OptionalOAuthAuthentication())
        authorization = AnonymousReadOnlyAuthorization()
        fields = ['rating', 'body']

        filtering = {
            'app': ('exact',),
            'user': ('exact',),
            'pk': ('exact',),
        }

        ordering = ['created']

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

    def obj_create(self, bundle, request=None, **kwargs):
        """
        Handle POST requests to the resource. If the data validates, create a
        new Review from bundle data.
        """
        form = ReviewForm(bundle.data)

        if not form.is_valid():
            raise self.form_errors(form)

        # Validate that the app exists.
        try:
            app = Webapp.objects.get(pk=bundle.data['app'])
        except Webapp.DoesNotExist:
            raise self.non_form_errors([('app', 'Invalid app')])

        # Return 409 if the user has already reviewed this app.
        if self._meta.queryset.filter(addon=app, user=request.user).exists():
            raise ImmediateHttpResponse(response=http.HttpConflict())

        # Return 403 if the user is attempting to review their own app:
        if app.has_author(request.user):
            raise ImmediateHttpResponse(response=http.HttpForbidden())

        # Return 403 if not a free app and the user hasn't purchased it.
        if app.is_premium() and not app.is_purchased(request.amo_user):
            raise ImmediateHttpResponse(response=http.HttpForbidden())

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
            raise ImmediateHttpResponse(response=http.HttpForbidden())

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
            addon = Addon.objects.get(pk=request.GET['app'])
            data['info'] = {
                'average': addon.average_rating,
                'slug': addon.app_slug
            }

            filters = dict(addon=addon)
            if addon.is_packaged:
                filters['version'] = addon.current_version

            if not request.user.is_anonymous():
                filters['user'] = request.user
                existing_review = Review.objects.valid().filter(**filters)
                data['user'] = {'can_rate': not addon.has_author(request.user),
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


class RatingFlagResource(MarketplaceModelResource):

    class Meta:
        queryset = ReviewFlag.objects.all()
        resource_name = 'rating_flag'
        list_allowed_methods = ['post']
        detail_allowed_methods = []
        authentication = OAuthAuthentication()
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
