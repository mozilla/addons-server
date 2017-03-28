from django import http
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.db.transaction import non_atomic_requests
from django.shortcuts import get_object_or_404, redirect
from django.utils.encoding import force_text
from django.utils.translation import ugettext as _

from mobility.decorators import mobile_template
from rest_framework import serializers
from rest_framework.decorators import detail_route
from rest_framework.exceptions import ParseError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import ModelViewSet

import olympia.core.logger
from olympia.amo.decorators import json_view, login_required, post_required
from olympia.amo import helpers
from olympia.amo.utils import render, paginate
from olympia.access import acl
from olympia.addons.decorators import addon_view_factory
from olympia.addons.models import Addon
from olympia.addons.views import AddonChildMixin
from olympia.api.permissions import (
    AllowAddonAuthor, AllowIfPublic, AllowOwner,
    AllowRelatedObjectPermissions, AnyOf, ByHttpMethod, GroupPermission)

from .helpers import user_can_delete_review
from .models import Review, ReviewFlag, GroupedRating
from .permissions import CanDeleteReviewPermission
from .serializers import ReviewSerializer, ReviewSerializerReply
from . import forms


log = olympia.core.logger.getLogger('z.reviews')
addon_view = addon_view_factory(qs=Addon.objects.valid)


@addon_view
@mobile_template('reviews/{mobile/}review_list.html')
@non_atomic_requests
def review_list(request, addon, review_id=None, user_id=None, template=None):
    qs = Review.without_replies.all().filter(
        addon=addon).order_by('-created')

    ctx = {'addon': addon,
           'grouped_ratings': GroupedRating.get(addon.id)}

    ctx['form'] = forms.ReviewForm(None)

    if review_id is not None:
        ctx['page'] = 'detail'
        # If this is a dev reply, find the first msg for context.
        review = get_object_or_404(Review.objects.all(), pk=review_id)
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

    ctx['reviews'] = reviews = paginate(request, qs)
    ctx['replies'] = Review.get_replies(reviews.object_list)
    if request.user.is_authenticated():
        ctx['review_perms'] = {
            'is_admin': acl.action_allowed(request, 'Addons', 'Edit'),
            'is_editor': acl.is_editor(request, addon),
            'is_author': acl.check_addon_ownership(request, addon, viewer=True,
                                                   dev=True, support=True),
        }
        ctx['flags'] = get_flags(request, reviews.object_list)
    else:
        ctx['review_perms'] = {}
    return render(request, template, ctx)


def get_flags(request, reviews):
    reviews = [r.id for r in reviews]
    qs = ReviewFlag.objects.filter(review__in=reviews, user=request.user.id)
    return dict((r.review_id, r) for r in qs)


@addon_view
@post_required
@login_required(redirect=False)
@json_view
def flag(request, addon, review_id):
    review = get_object_or_404(Review.objects, pk=review_id, addon=addon)
    if review.user_id == request.user.id:
        raise PermissionDenied
    d = dict(review=review_id, user=request.user.id)
    try:
        instance = ReviewFlag.objects.get(**d)
    except ReviewFlag.DoesNotExist:
        instance = None
    data = dict(request.POST.items(), **d)
    form = forms.ReviewFlagForm(data, instance=instance)
    if form.is_valid():
        form.save()
        Review.objects.filter(id=review_id).update(editorreview=True)
        return {'msg': _('Thanks; this review has been flagged '
                         'for editor approval.')}
    else:
        return json_view.error(form.errors)


@addon_view
@post_required
@login_required(redirect=False)
def delete(request, addon, review_id):
    review = get_object_or_404(Review.objects, pk=review_id, addon=addon)
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
    is_admin = acl.action_allowed(request, 'Addons', 'Edit')
    is_author = acl.check_addon_ownership(request, addon, dev=True)
    if not (is_admin or is_author):
        raise PermissionDenied

    review = get_object_or_404(Review.objects, pk=review_id, addon=addon)
    form = forms.ReviewReplyForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        kwargs = {
            'reply_to': review,
            'addon': addon,
            'defaults': _review_details(request, addon, form)
        }
        reply, created = Review.unfiltered.update_or_create(**kwargs)
        return redirect(helpers.url('addons.reviews.detail', addon.slug,
                                    review_id))
    ctx = {
        'review': review,
        'form': form,
        'addon': addon
    }
    return render(request, 'reviews/reply.html', ctx)


@addon_view
@mobile_template('reviews/{mobile/}add.html')
@login_required
def add(request, addon, template=None):
    if addon.has_author(request.user):
        raise PermissionDenied
    form = forms.ReviewForm(request.POST or None)
    if (request.method == 'POST' and form.is_valid() and
            not request.POST.get('detailed')):
        details = _review_details(request, addon, form)
        review = Review.objects.create(**details)
        if 'flag' in form.cleaned_data and form.cleaned_data['flag']:
            rf = ReviewFlag(review=review,
                            user_id=request.user.id,
                            flag=ReviewFlag.OTHER,
                            note='URLs')
            rf.save()
        return redirect(helpers.url('addons.reviews.list', addon.slug))
    return render(request, template, dict(addon=addon, form=form))


@addon_view
@json_view
@login_required(redirect=False)
@post_required
def edit(request, addon, review_id):
    review = get_object_or_404(Review.objects, pk=review_id, addon=addon)
    is_admin = acl.action_allowed(request, 'Addons', 'Edit')
    if not (request.user.id == review.user.id or is_admin):
        raise PermissionDenied
    cls = forms.ReviewReplyForm if review.reply_to else forms.ReviewForm
    form = cls(request.POST)
    if form.is_valid():
        data = _review_details(request, addon, form, create=False)
        for field, value in data.items():
            setattr(review, field, value)
        # Resist the temptation to use review.update(): it'd be more direct but
        # doesn't work with extra fields that are not meant to be saved like
        # 'user_responsible'.
        review.save()
        return {}
    else:
        return json_view.error(form.errors)


class ReviewViewSet(AddonChildMixin, ModelViewSet):
    serializer_class = ReviewSerializer
    permission_classes = [
        ByHttpMethod({
            'get': AllowAny,
            'head': AllowAny,
            'options': AllowAny,  # Needed for CORS.

            # Deletion requires a specific permission check.
            'delete': CanDeleteReviewPermission,

            # To post a review you just need to be authenticated.
            'post': IsAuthenticated,

            # To edit a review you need to be the author or be an admin.
            'patch': AnyOf(AllowOwner, GroupPermission('Addons', 'Edit')),

            # Implementing PUT would be a little incoherent as we don't want to
            # allow users to change `version` but require it at creation time.
            # So only PATCH is allowed for editing.
        }),
    ]
    reply_permission_classes = [AnyOf(
        GroupPermission('Addons', 'Edit'),
        AllowRelatedObjectPermissions('addon', [AllowAddonAuthor]),
    )]
    reply_serializer_class = ReviewSerializerReply

    queryset = Review.objects.all()

    def set_addon_object_from_review(self, review):
        """Set addon object on the instance from a review object."""
        # At this point it's likely we didn't have an addon in the request, so
        # if we went through get_addon_object() before it's going to be set
        # to None already. We delete the addon_object property cache and set
        # addon_pk in kwargs to force get_addon_object() to reset
        # self.addon_object.
        del self.addon_object
        self.kwargs['addon_pk'] = str(review.addon.pk)
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
        return super(ReviewViewSet, self).get_addon_object(
            permission_classes=[AllowIfPublic])

    def check_permissions(self, request):
        """Perform permission checks.

        The regular DRF permissions checks are made, but also, before that, if
        an addon was requested, verify that it exists, is public and listed,
        through AllowIfPublic permission, that get_addon_object() uses."""
        self.get_addon_object()

        # Proceed with the regular permission checks.
        return super(ReviewViewSet, self).check_permissions(request)

    def get_serializer(self, *args, **kwargs):
        if self.action in ('partial_update', 'update'):
            instance = args[0]
            if instance.reply_to is not None:
                self.review_object = instance.reply_to
                self.serializer_class = self.reply_serializer_class
        return super(ReviewViewSet, self).get_serializer(*args, **kwargs)

    def filter_queryset(self, qs):
        if self.action == 'list':
            addon_identifier = self.request.GET.get('addon')
            user_identifier = self.request.GET.get('user')
            if addon_identifier:
                qs = qs.filter(is_latest=True, addon=self.get_addon_object())
            if user_identifier:
                try:
                    user_identifier = int(user_identifier)
                except ValueError:
                    raise ParseError('user parameter should be an integer.')
                qs = qs.filter(user=user_identifier)
            if not addon_identifier and not user_identifier:
                # Don't allow listing reviews without filtering by add-on or
                # user.
                raise ParseError('Need an addon or user parameter')
        return qs

    def get_paginated_response(self, data):
        response = super(ReviewViewSet, self).get_paginated_response(data)
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
        requested = self.request.GET.get('filter')

        # Add this as a property of the view, because we need to pass down the
        # information to the serializer to show/hide delete replies.
        if not hasattr(self, 'should_access_deleted_reviews'):
            self.should_access_deleted_reviews = (
                (requested == 'with_deleted' or self.action != 'list') and
                self.request.user.is_authenticated() and
                acl.action_allowed(self.request, 'Addons', 'Edit'))

        should_access_only_top_level_reviews = (
            self.action == 'list' and self.get_addon_object())

        if self.should_access_deleted_reviews:
            # For admins or add-on authors replying. When listing, we include
            # deleted reviews but still filter out out replies, because they'll
            # be in the serializer anyway. For other actions, we simply remove
            # any filtering, allowing them to access any review out of the box
            # with no extra parameter needed.
            if self.action == 'list':
                self.queryset = Review.unfiltered.filter(reply_to__isnull=True)
            else:
                self.queryset = Review.unfiltered.all()
        elif should_access_only_top_level_reviews:
            # When listing add-on reviews, exclude replies, they'll be
            # included during serialization as children of the relevant
            # reviews instead.
            self.queryset = Review.without_replies.all()

        qs = super(ReviewViewSet, self).get_queryset()
        # The serializer needs reply, version (only the "version" field) and
        # user. We don't need much for version and user, so we can make joins
        # with select_related(), but for replies additional queries will be
        # made for translations anyway so we're better off using
        # prefetch_related() to make a separate query to fetch them all.
        qs = qs.select_related('version__version', 'user')
        replies_qs = Review.unfiltered.select_related('user')
        return qs.prefetch_related(Prefetch('reply', queryset=replies_qs))

    @detail_route(
        methods=['post'], permission_classes=reply_permission_classes,
        serializer_class=reply_serializer_class)
    def reply(self, *args, **kwargs):
        # A reply is just like a regular post, except that we set the reply
        # FK to the current review object and only allow add-on authors/admins.
        # Call get_object() to trigger 404 if it does not exist.
        self.review_object = self.get_object()
        self.set_addon_object_from_review(self.review_object)
        if Review.unfiltered.filter(reply_to=self.review_object).exists():
            # A reply already exists, just edit it.
            # We set should_access_deleted_reviews so that it works even if
            # the reply has been deleted.
            self.kwargs['pk'] = kwargs['pk'] = self.review_object.reply.pk
            self.should_access_deleted_reviews = True
            return self.partial_update(*args, **kwargs)
        return self.create(*args, **kwargs)

    @detail_route(methods=['post'])
    def flag(self, request, *args, **kwargs):
        # We load the add-on object from the review to trigger permission
        # checks.
        self.review_object = self.get_object()
        self.set_addon_object_from_review(self.review_object)

        # Re-use flag view since it's already returning json. We just need to
        # pass it the addon slug (passing it the PK would result in a redirect)
        # and make sure request.POST is set with whatever data was sent to the
        # DRF view.
        request._request.POST = request.data
        request = request._request
        response = flag(request, self.addon_object.slug, kwargs.get('pk'))
        if response.status_code == 200:
            response.content = ''
            response.status_code = 202
        return response

    def perform_destroy(self, instance):
        instance.delete(user_responsible=self.request.user)
