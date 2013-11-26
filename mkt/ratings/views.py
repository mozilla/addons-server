from django.core.paginator import Paginator

import commonware.log
from rest_framework.decorators import action
from rest_framework.exceptions import (MethodNotAllowed, NotAuthenticated,
                                       ParseError)
from rest_framework.mixins import CreateModelMixin
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.serializers import ValidationError
from rest_framework.viewsets import GenericViewSet, ModelViewSet

import amo
from lib.metrics import record_action
from reviews.models import Review, ReviewFlag

from mkt.api.authentication import (RestAnonymousAuthentication,
                                    RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.authorization import (AnyOf, AllowOwner, AllowRelatedAppOwner,
                                   ByHttpMethod, GroupPermission)
from mkt.api.base import CORSMixin
from mkt.ratings.serializers import RatingFlagSerializer, RatingSerializer


log = commonware.log.getLogger('z.api')


class RatingPaginator(Paginator):
    # FIXME: This is only right when ?app= filtering is applied, if no
    # filtering or if ?user= filtering is done, it's completely wrong.
    @property
    def count(self):
        try:
            r = self.object_list[0]
        except IndexError:
            return 0
        return r.addon.total_reviews


class RatingViewSet(CORSMixin, ModelViewSet):
    # Unfortunately, the model class name for ratings is "Review".
    queryset = Review.objects.valid()
    cors_allowed_methods = ('get', 'post', 'put', 'delete')
    permission_classes = [ByHttpMethod({
        'options': AllowAny,  # Needed for CORS.
        'get': AllowAny,
        'post': IsAuthenticated,
        'put': AllowOwner,
        'delete': AnyOf(AllowOwner,
                        AllowRelatedAppOwner,
                        GroupPermission('Users', 'Edit'),
                        GroupPermission('Addons', 'Edit')),
    })]
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]
    serializer_class = RatingSerializer
    paginator_class = RatingPaginator

    # FIXME: Add throttling ? Original tastypie version didn't have it...

    def get_queryset(self):
        qs = super(RatingViewSet, self).get_queryset()
        # Mature regions show only reviews from within that region.
        # FIXME: what is client_data, how is it filled ? There was no tests
        # for this.
        if not self.request.REGION.adolescent:
            qs = qs.filter(client_data__region=self.request.REGION.id)
        return qs

    def paginate_queryset(self, queryset, page_size=None):
        page_query_param = self.request.QUERY_PARAMS.get(self.page_kwarg)
        offset_query_param = self.request.QUERY_PARAMS.get('offset')

        # If 'offset' (tastypie-style pagination) parameter is present and
        # 'page' isn't, use offset it to find which page to use.
        if page_query_param is None and offset_query_param is not None:
            page_number = int(offset_query_param) / self.get_paginate_by() + 1
            self.kwargs[self.page_kwarg] = page_number
        return super(RatingViewSet, self).paginate_queryset(queryset,
            page_size=page_size)

    def filter_queryset(self, queryset):
        """
        Custom filter method allowing us to filter on app slug/pk and user pk
        (or the special user value "mine"). A full FilterSet is overkill here.
        """
        filters = {}
        app = self.request.GET.get('app')
        user = self.request.GET.get('user')
        if app:
            self.app = self.get_app(app)
            filters['addon'] = self.app
        if user:
            filters['user'] = self.get_user(user)

        if filters:
            queryset = queryset.filter(**filters)
        return queryset

    def get_user(self, ident):
        pk = ident
        if pk == 'mine':
            user = amo.get_user()
            if not user:
                # You must be logged in to use "mine".
                raise NotAuthenticated()
            pk = user.pk
        return pk

    def get_app(self, ident):
        try:
            return self.serializer_class.get_app_from_value(ident)
        except ValidationError as e:
            raise ParseError(detail=e.messages[0])

    def list(self, request, *args, **kwargs):
        response = super(RatingViewSet, self).list(request, *args, **kwargs)
        app = getattr(self, 'app', None)
        if app:
            user, info = self.get_extra_data(app, request.amo_user)
            response.data['user'] = user
            response.data['info'] = info
        return response

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        amo.log(amo.LOG.DELETE_REVIEW, obj.addon, obj)
        log.debug('[Review:%s] Deleted by %s' %
            (obj.pk, self.request.amo_user.id))
        return super(RatingViewSet, self).destroy(request, *args, **kwargs)

    def post_save(self, obj, created=False):
        app = obj.addon
        if created:
            amo.log(amo.LOG.ADD_REVIEW, app, obj)
            log.debug('[Review:%s] Created by user %s ' %
                      (obj.pk, self.request.amo_user.id))
            record_action('new-review', self.request, {'app-id': app.id})
        else:
            amo.log(amo.LOG.EDIT_REVIEW, app, obj)
            log.debug('[Review:%s] Edited by %s' %
                      (obj.pk, self.request.amo_user.id))

    def partial_update(self, *args, **kwargs):
        # We don't need/want PATCH.
        raise MethodNotAllowed('PATCH is not supported for this endpoint.')

    def get_extra_data(self, app, amo_user):
        extra_user = None

        if amo_user and not amo_user.is_anonymous():
            if app.is_premium():
                # If the app is premium, you need to purchase it to rate it.
                can_rate = app.has_purchased(amo_user)
            else:
                # If the app is free, you can not be one of the authors.
                can_rate = not app.has_author(amo_user)

            filters = {
                'addon': app,
                'user': amo_user
            }
            if app.is_packaged:
                filters['version'] = app.current_version

            extra_user = {
                'can_rate': can_rate,
                'has_rated': Review.objects.valid().filter(**filters).exists()
            }

        extra_info = {
            'average': app.average_rating,
            'slug': app.app_slug,
            'current_version': app.current_version.version
        }

        return extra_user, extra_info

    @action(methods=['POST'], permission_classes=[AllowAny])
    def flag(self, request, pk=None):
        self.kwargs[self.lookup_field] = pk
        self.get_object()  # Will check that the Review instance is valid.
        request._request.CORS = RatingFlagViewSet.cors_allowed_methods
        view = RatingFlagViewSet.as_view({'post': 'create'})
        return view(request, *self.args, **{'review': pk})


class RatingFlagViewSet(CORSMixin, CreateModelMixin, GenericViewSet):
    queryset = ReviewFlag.objects.all()
    cors_allowed_methods = ('post',)
    permission_classes = [AllowAny]
    authentication_classes = [RestAnonymousAuthentication]
    serializer_class = RatingFlagSerializer

    def post_save(self, obj, created=False):
        review = self.kwargs['review']
        Review.objects.filter(id=review).update(editorreview=True)
