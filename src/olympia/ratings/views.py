from django import http
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch, Q
from django.db.transaction import non_atomic_requests
from django.shortcuts import get_object_or_404, redirect
from django.utils.encoding import force_text
from django.utils.translation import ugettext

from rest_framework import serializers
from rest_framework.decorators import detail_route
from rest_framework.exceptions import ParseError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import ModelViewSet

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.addons.decorators import addon_view_factory
from olympia.addons.models import Addon
from olympia.addons.views import AddonChildMixin
from olympia.amo.decorators import json_view, login_required, post_required
from olympia.amo.templatetags import jinja_helpers
from olympia.amo.utils import paginate, render
from olympia.api.pagination import OneOrZeroPageNumberPagination
from olympia.api.permissions import (
    AllowAddonAuthor, AllowIfPublic, AllowOwner, AllowRelatedObjectPermissions,
    AnyOf, ByHttpMethod, GroupPermission)
from olympia.api.throttling import GranularUserRateThrottle

from . import forms
from .models import GroupedRating, Rating, RatingFlag
from .permissions import CanDeleteRatingPermission
from .serializers import RatingSerializer, RatingSerializerReply
from .templatetags.jinja_helpers import user_can_delete_review


addon_view = addon_view_factory(qs=Addon.objects.valid)


@addon_view
@non_atomic_requests
def review_list(request, addon, review_id=None, user_id=None):
    qs = Rating.without_replies.all().filter(
        addon=addon).order_by('-created')

    ctx = {'addon': addon,
           'grouped_ratings': GroupedRating.get(addon.id)}

    ctx['form'] = forms.RatingForm(None)
    is_admin = acl.action_allowed(request, amo.permissions.ADDONS_EDIT)

    if review_id is not None:
        ctx['page'] = 'detail'
        # If this is a dev reply, find the first msg for context.
        review = get_object_or_404(Rating.objects.all(), pk=review_id)
        if review.reply_to_id:
            review_id = review.reply_to_id
            ctx['reply'] = review
        qs = qs.filter(pk=review_id)
    elif user_id is not None:
        ctx['page'] = 'user'
        qs = qs.filter(user=user_id)
        if not qs:
            raise http.Http404()
    else:
        ctx['page'] = 'list'
        qs = qs.filter(is_latest=True)
        # Don't filter out empty reviews for admins.
        if not is_admin:
            # But otherwise, filter out everyone elses empty reviews.
            user_filter = (Q(user=request.user.pk)
                           if request.user.is_authenticated() else Q())
            qs = qs.filter(~Q(body=None) | user_filter)

    ctx['reviews'] = reviews = paginate(request, qs)
    ctx['replies'] = Rating.get_replies(reviews.object_list)
    if request.user.is_authenticated():
        ctx['review_perms'] = {
            'is_admin': is_admin,
            'is_reviewer': acl.action_allowed(
                request, amo.permissions.RATINGS_MODERATE),
            'is_author': acl.check_addon_ownership(request, addon, dev=True),
        }
        ctx['flags'] = get_flags(request, reviews.object_list)
    else:
        ctx['review_perms'] = {}
    return render(request, 'ratings/review_list.html', ctx)


def get_flags(request, reviews):
    reviews = [r.id for r in reviews]
    qs = RatingFlag.objects.filter(rating__in=reviews, user=request.user.id)
    return {obj.rating_id: obj for obj in qs}


@addon_view
@post_required
@login_required(redirect=False)
@json_view
def flag(request, addon, review_id):
    review = get_object_or_404(Rating.objects, pk=review_id, addon=addon)
    if review.user_id == request.user.id:
        raise PermissionDenied
    if not review.body:
        return {'msg': ugettext('This rating can\'t be flagged because it has '
                                'no review text.')}
    data = {'rating': review_id, 'user': request.user.id}
    try:
        instance = RatingFlag.objects.get(**data)
    except RatingFlag.DoesNotExist:
        instance = None
    data = dict(request.POST.items(), **data)
    form = forms.RatingFlagForm(data, instance=instance)
    if form.is_valid():
        form.save()
        Rating.objects.filter(id=review_id).update(editorreview=True)
        return {'msg': ugettext('Thanks; this review has been flagged '
                                'for reviewer approval.')}
    else:
        return json_view.error(form.errors)


@addon_view
@post_required
@login_required(redirect=False)
def delete(request, addon, review_id):
    review = get_object_or_404(Rating.objects, pk=review_id, addon=addon)
    if not user_can_delete_review(request, review):
        raise PermissionDenied
    review.delete(user_responsible=request.user)
    return http.HttpResponse()


def _review_details(request, addon, form, create=True):
    data = {
        # Always set deleted: False because when replying, you're actually
        # editing the previous reply if it existed, even if it had been
        # deleted.
        'deleted': False,

        # This field is not saved, but it helps the model know that the action
        # should be logged.
        'user_responsible': request.user,
    }
    if create:
        # These fields should be set at creation time.
        data['addon'] = addon
        data['user'] = request.user
        data['version'] = addon.current_version
        data['ip_address'] = request.META.get('REMOTE_ADDR', '')
    data.update(**form.cleaned_data)
    return data


@addon_view
@login_required
def reply(request, addon, review_id):
    is_admin = acl.action_allowed(request, amo.permissions.ADDONS_EDIT)
    is_author = acl.check_addon_ownership(request, addon, dev=True)
    if not (is_admin or is_author):
        raise PermissionDenied

    rating = get_object_or_404(Rating.objects, pk=review_id, addon=addon)
    form = forms.RatingReplyForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        kwargs = {
            'reply_to': rating,
            'addon': addon,
            'defaults': _review_details(request, addon, form)
        }
        reply, created = Rating.unfiltered.update_or_create(**kwargs)
        return redirect(jinja_helpers.url(
            'addons.ratings.detail', addon.slug, review_id))
    ctx = {
        'review': rating,
        'form': form,
        'addon': addon
    }
    return render(request, 'ratings/reply.html', ctx)


@addon_view
@login_required
def add(request, addon):
    if addon.has_author(request.user):
        raise PermissionDenied
    form = forms.RatingForm(request.POST or None)
    if (request.method == 'POST' and form.is_valid() and
            not request.POST.get('detailed')):
        details = _review_details(request, addon, form)
        rating = Rating.objects.create(**details)
        if 'flag' in form.cleaned_data and form.cleaned_data['flag']:
            rf = RatingFlag(rating=rating,
                            user_id=request.user.id,
                            flag=RatingFlag.OTHER,
                            note='URLs')
            rf.save()
        return redirect(jinja_helpers.url('addons.ratings.list', addon.slug))
    return render(request, 'ratings/add.html', {'addon': addon, 'form': form})


@addon_view
@json_view
@login_required(redirect=False)
@post_required
def edit(request, addon, review_id):
    rating = get_object_or_404(Rating.objects, pk=review_id, addon=addon)
    is_admin = acl.action_allowed(request, amo.permissions.ADDONS_EDIT)
    if not (request.user.id == rating.user.id or is_admin):
        raise PermissionDenied
    cls = forms.RatingReplyForm if rating.reply_to else forms.RatingForm
    form = cls(request.POST)
    if form.is_valid():
        data = _review_details(request, addon, form, create=False)
        for field, value in data.items():
            setattr(rating, field, value)
        # Resist the temptation to use rating.update(): it'd be more direct but
        # doesn't work with extra fields that are not meant to be saved like
        # 'user_responsible'.
        rating.save()
        return {}
    else:
        return json_view.error(form.errors)


class RatingThrottle(GranularUserRateThrottle):
    rate = '1/minute'
    scope = 'user_rating'

    def allow_request(self, request, view):
        if request.method.lower() == 'post':
            return super(RatingThrottle, self).allow_request(request, view)
        else:
            return True


class RatingReplyThrottle(RatingThrottle):
    rate = '1/5second'


class RatingViewSet(AddonChildMixin, ModelViewSet):
    serializer_class = RatingSerializer
    permission_classes = [
        ByHttpMethod({
            'get': AllowAny,
            'head': AllowAny,
            'options': AllowAny,  # Needed for CORS.

            # Deletion requires a specific permission check.
            'delete': CanDeleteRatingPermission,

            # To post a rating you just need to be authenticated.
            'post': IsAuthenticated,

            # To edit a rating you need to be the author or be an admin.
            'patch': AnyOf(AllowOwner, GroupPermission(
                amo.permissions.ADDONS_EDIT)),

            # Implementing PUT would be a little incoherent as we don't want to
            # allow users to change `version` but require it at creation time.
            # So only PATCH is allowed for editing.
        }),
    ]
    reply_permission_classes = [AnyOf(
        GroupPermission(amo.permissions.ADDONS_EDIT),
        AllowRelatedObjectPermissions('addon', [AllowAddonAuthor]),
    )]
    reply_serializer_class = RatingSerializerReply
    throttle_classes = (RatingThrottle,)

    def set_addon_object_from_rating(self, rating):
        """Set addon object on the instance from a rating object."""
        # At this point it's likely we didn't have an addon in the request, so
        # if we went through get_addon_object() before it's going to be set
        # to None already. We delete the addon_object property cache and set
        # addon_pk in kwargs to force get_addon_object() to reset
        # self.addon_object.
        del self.addon_object
        self.kwargs['addon_pk'] = str(rating.addon.pk)
        return self.get_addon_object()

    def get_addon_object(self):
        """Return addon object associated with the request, or None if not
        relevant.

        Will also fire permission checks on the addon object when it's loaded.
        """
        if hasattr(self, 'addon_object'):
            return self.addon_object

        if 'addon_pk' not in self.kwargs:
            self.kwargs['addon_pk'] = (
                self.request.data.get('addon') or
                self.request.GET.get('addon'))
        if not self.kwargs['addon_pk']:
            # If we don't have an addon object, set it as None on the instance
            # and return immediately, that's fine.
            self.addon_object = None
            return
        else:
            # AddonViewSet.get_lookup_field() expects a string.
            self.kwargs['addon_pk'] = force_text(self.kwargs['addon_pk'])
        # When loading the add-on, pass a specific permission class - the
        # default from AddonViewSet is too restrictive, we are not modifying
        # the add-on itself so we don't need all the permission checks it does.
        return super(RatingViewSet, self).get_addon_object(
            permission_classes=[AllowIfPublic])

    def check_permissions(self, request):
        """Perform permission checks.

        The regular DRF permissions checks are made, but also, before that, if
        an addon was requested, verify that it exists, is public and listed,
        through AllowIfPublic permission, that get_addon_object() uses."""
        self.get_addon_object()

        # Proceed with the regular permission checks.
        return super(RatingViewSet, self).check_permissions(request)

    def get_serializer(self, *args, **kwargs):
        if self.action in ('partial_update', 'update'):
            instance = args[0]
            if instance.reply_to is not None:
                self.rating_object = instance.reply_to
                self.serializer_class = self.reply_serializer_class
        return super(RatingViewSet, self).get_serializer(*args, **kwargs)

    def filter_queryset(self, qs):
        if self.action == 'list':
            addon_identifier = self.request.GET.get('addon')
            user_identifier = self.request.GET.get('user')
            version_identifier = self.request.GET.get('version')
            if addon_identifier:
                qs = qs.filter(addon=self.get_addon_object())
            if user_identifier:
                try:
                    user_identifier = int(user_identifier)
                except ValueError:
                    raise ParseError('user parameter should be an integer.')
                qs = qs.filter(user=user_identifier)
            if version_identifier:
                try:
                    version_identifier = int(version_identifier)
                except ValueError:
                    raise ParseError('version parameter should be an integer.')
                qs = qs.filter(version=version_identifier)
            elif addon_identifier:
                # When filtering on addon but not on version, only return the
                # latest rating posted by each user.
                qs = qs.filter(is_latest=True)
            if not addon_identifier and not user_identifier:
                # Don't allow listing ratings without filtering by add-on or
                # user.
                raise ParseError('Need an addon or user parameter')
            if user_identifier and addon_identifier and version_identifier:
                # When user, addon and version identifiers are set, we are
                # effectively only looking for one or zero objects. Fake
                # pagination in that case, avoiding all count() calls and
                # therefore related cache-machine invalidation issues. Needed
                # because the frontend wants to call this before and after
                # having posted a new rating, and needs accurate results.
                self.pagination_class = OneOrZeroPageNumberPagination
        return super(RatingViewSet, self).filter_queryset(qs)

    def get_paginated_response(self, data):
        response = super(RatingViewSet, self).get_paginated_response(data)
        if 'show_grouped_ratings' in self.request.GET:
            try:
                show_grouped_ratings = (
                    serializers.BooleanField().to_internal_value(
                        self.request.GET['show_grouped_ratings']))
            except serializers.ValidationError:
                raise ParseError(
                    'show_grouped_ratings parameter should be a boolean')
            if show_grouped_ratings and self.get_addon_object():
                response.data['grouped_ratings'] = dict(GroupedRating.get(
                    self.addon_object.id))
        return response

    def get_queryset(self):
        requested = self.request.GET.get('filter', '').split(',')
        has_addons_edit = acl.action_allowed(self.request,
                                             amo.permissions.ADDONS_EDIT)

        # Add this as a property of the view, because we need to pass down the
        # information to the serializer to show/hide delete replies.
        if not hasattr(self, 'should_access_deleted_ratings'):
            self.should_access_deleted_ratings = (
                ('with_deleted' in requested or self.action != 'list') and
                self.request.user.is_authenticated() and
                has_addons_edit)

        should_access_only_top_level_ratings = (
            self.action == 'list' and self.get_addon_object())

        if self.should_access_deleted_ratings:
            # For admins or add-on authors replying. When listing, we include
            # deleted ratings but still filter out out replies, because they'll
            # be in the serializer anyway. For other actions, we simply remove
            # any filtering, allowing them to access any rating out of the box
            # with no extra parameter needed.
            if self.action == 'list':
                queryset = Rating.unfiltered.filter(reply_to__isnull=True)
            else:
                queryset = Rating.unfiltered.all()
        elif should_access_only_top_level_ratings:
            # When listing add-on ratings, exclude replies, they'll be
            # included during serialization as children of the relevant
            # ratings instead.
            queryset = Rating.without_replies.all()
        else:
            queryset = Rating.objects.all()

        # Filter out empty ratings if specified.
        # Should the users own empty ratings be filtered back in?
        if 'with_yours' in requested and self.request.user.is_authenticated():
            user_filter = Q(user=self.request.user.pk)
        else:
            user_filter = Q()
        # Apply the filter(s)
        if 'without_empty_body' in requested:
            queryset = queryset.filter(~Q(body=None) | user_filter)

        # The serializer needs reply, version (only the "version" field) and
        # user. We don't need much for version and user, so we can make joins
        # with select_related(), but for replies additional queries will be
        # made for translations anyway so we're better off using
        # prefetch_related() to make a separate query to fetch them all.
        queryset = queryset.select_related('version__version', 'user')
        replies_qs = Rating.unfiltered.select_related('user')
        return queryset.prefetch_related(
            Prefetch('reply', queryset=replies_qs))

    @detail_route(
        methods=['post'], permission_classes=reply_permission_classes,
        serializer_class=reply_serializer_class,
        throttle_classes=[RatingReplyThrottle])
    def reply(self, *args, **kwargs):
        # A reply is just like a regular post, except that we set the reply
        # FK to the current rating object and only allow add-on authors/admins.
        # Call get_object() to trigger 404 if it does not exist.
        self.rating_object = self.get_object()
        self.set_addon_object_from_rating(self.rating_object)
        if Rating.unfiltered.filter(reply_to=self.rating_object).exists():
            # A reply already exists, just edit it.
            # We set should_access_deleted_ratings so that it works even if
            # the reply has been deleted.
            self.kwargs['pk'] = kwargs['pk'] = self.rating_object.reply.pk
            self.should_access_deleted_ratings = True
            return self.partial_update(*args, **kwargs)
        return self.create(*args, **kwargs)

    @detail_route(methods=['post'], throttle_classes=[])
    def flag(self, request, *args, **kwargs):
        # We load the add-on object from the rating to trigger permission
        # checks.
        self.rating_object = self.get_object()
        self.set_addon_object_from_rating(self.rating_object)

        # Re-use flag view since it's already returning json. We just need to
        # pass it the addon slug (passing it the PK would result in a redirect)
        # and make sure request.POST is set with whatever data was sent to the
        # DRF view.
        request._request.POST = request.data
        request = request._request
        response = flag(request, self.addon_object.slug, kwargs.get('pk'))
        if response.status_code == 200:
            # 202 is a little better than 200: we're accepting the request, but
            # make no promises to act on it :)
            response.status_code = 202
        return response

    def perform_destroy(self, instance):
        instance.delete(user_responsible=self.request.user)
