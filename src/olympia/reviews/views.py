import HTMLParser
import json
import requests

from django import http
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.transaction import non_atomic_requests
from django.shortcuts import get_object_or_404, redirect
from django.template import Context, loader
from django.utils.http import urlquote
from django.utils.translation import ugettext as _

import commonware.log
from mobility.decorators import mobile_template
from rest_framework.decorators import detail_route
from rest_framework.exceptions import ParseError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import ModelViewSet
from waffle.decorators import waffle_switch

from olympia import amo
from olympia.amo import messages
from olympia.amo.decorators import (
    json_view, login_required, post_required, restricted_content)
from olympia.amo import helpers
from olympia.amo.utils import render, paginate, send_mail as amo_send_mail
from olympia.access import acl
from olympia.addons.decorators import addon_view_factory
from olympia.addons.models import Addon
from olympia.addons.views import AddonChildMixin
from olympia.api.permissions import (
    AllowAddonAuthor, AllowIfReviewedAndListed, AllowOwner,
    AllowRelatedObjectPermissions, AnyOf, ByHttpMethod, GroupPermission)

from .helpers import user_can_delete_review
from .models import Review, ReviewFlag, GroupedRating, Spam
from .permissions import CanDeleteReviewPermission
from .serializers import ReviewSerializer, ReviewSerializerReply
from . import forms


log = commonware.log.getLogger('z.reviews')
addon_view = addon_view_factory(qs=Addon.objects.valid)


def send_mail(template, subject, emails, context, perm_setting):
    template = loader.get_template(template)
    amo_send_mail(
        subject, template.render(Context(context, autoescape=False)),
        recipient_list=emails, perm_setting=perm_setting)


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


def _retrieve_translation(text, language):
    try:
        r = requests.get(
            settings.GOOGLE_TRANSLATE_API_URL, params={
                'key': getattr(settings, 'GOOGLE_API_CREDENTIALS', ''),
                'q': text, 'target': language})
    except Exception, e:
        log.error(e)
    try:
        translated = (HTMLParser.HTMLParser().unescape(r.json()['data']
                      ['translations'][0]['translatedText']))
    except (KeyError, IndexError):
        translated = ''
    return translated, r


@addon_view
@waffle_switch('reviews-translate')
@non_atomic_requests
def translate(request, addon, review_id, language):
    """
    Use the Google Translate API for ajax, redirect to Google Translate for
    non ajax calls.
    """
    review = get_object_or_404(Review, pk=review_id, addon=addon)
    if '-' in language:
        language = language.split('-')[0]

    if request.is_ajax():
        title, r = _retrieve_translation(review.title, language)
        body, r = _retrieve_translation(review.body, language)
        return http.HttpResponse(json.dumps({'title': title, 'body': body}),
                                 status=r.status_code)
    else:
        return redirect(settings.GOOGLE_TRANSLATE_REDIRECT_URL.format(
            lang=language, text=urlquote(review.body)))


@addon_view
@post_required
@login_required(redirect=False)
@json_view
def flag(request, addon, review_id):
    review = get_object_or_404(Review, pk=review_id, addon=addon)
    if review.user_id == request.user.id:
        raise http.Http404()
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
        return json_view.error(unicode(form.errors))


@addon_view
@post_required
@login_required(redirect=False)
def delete(request, addon, review_id):
    review = get_object_or_404(Review.objects, pk=review_id, addon=addon)
    if not user_can_delete_review(request, review):
        raise PermissionDenied
    review.delete()

    log.info(u'Review deleted: %s deleted id:%s by %s ("%s": "%s")' %
             (request.user.name, review_id, review.user.name, review.title,
              review.body))
    return http.HttpResponse()


def _review_details(request, addon, form):
    version = addon.current_version and addon.current_version.id
    d = dict(addon_id=addon.id, user_id=request.user.id,
             version_id=version,
             ip_address=request.META.get('REMOTE_ADDR', ''))
    d.update(**form.cleaned_data)
    return d


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
        d = dict(reply_to=review, addon=addon,
                 defaults=dict(user=request.user))
        reply, new = Review.objects.get_or_create(**d)
        for key, val in _review_details(request, addon, form).items():
            setattr(reply, key, val)
        reply.save()
        action = 'New' if new else 'Edited'
        log.debug('%s reply to %s: %s' % (action, review_id, reply.id))

        if new:
            reply_url = helpers.url('addons.reviews.detail', addon.slug,
                                    review.id, add_prefix=False)
            data = {'name': addon.name,
                    'reply_title': reply.title,
                    'reply': reply.body,
                    'reply_url': helpers.absolutify(reply_url)}
            emails = [review.user.email]
            sub = u'Mozilla Add-on Developer Reply: %s' % addon.name
            send_mail('reviews/emails/reply_review.ltxt',
                      sub, emails, Context(data), 'reply')

        return redirect(helpers.url('addons.reviews.detail', addon.slug,
                                    review_id))
    ctx = dict(review=review, form=form, addon=addon)
    return render(request, 'reviews/reply.html', ctx)


@addon_view
@mobile_template('reviews/{mobile/}add.html')
@login_required
@restricted_content
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

        amo.log(amo.LOG.ADD_REVIEW, addon, review)
        log.debug('New review: %s' % review.id)

        reply_url = helpers.url('addons.reviews.reply', addon.slug, review.id,
                                add_prefix=False)
        data = {'name': addon.name,
                'rating': '%s out of 5 stars' % details['rating'],
                'review': details['body'],
                'reply_url': helpers.absolutify(reply_url)}

        emails = [a.email for a in addon.authors.all()]
        send_mail('reviews/emails/add_review.ltxt',
                  u'Mozilla Add-on User Review: %s' % addon.name,
                  emails, Context(data), 'new_review')

        return redirect(helpers.url('addons.reviews.list', addon.slug))
    return render(request, template, dict(addon=addon, form=form))


@addon_view
@json_view
@login_required(redirect=False)
@post_required
def edit(request, addon, review_id):
    review = get_object_or_404(Review, pk=review_id, addon=addon)
    is_admin = acl.action_allowed(request, 'Addons', 'Edit')
    if not (request.user.id == review.user.id or is_admin):
        raise PermissionDenied
    cls = forms.ReviewReplyForm if review.reply_to else forms.ReviewForm
    form = cls(request.POST)
    if form.is_valid():
        for field in form.fields:
            if field in form.cleaned_data:
                setattr(review, field, form.cleaned_data[field])
        amo.log(amo.LOG.EDIT_REVIEW, addon, review)
        review.save()
        return {}
    else:
        return json_view.error(form.errors)


@login_required
def spam(request):
    if not acl.action_allowed(request, 'Spam', 'Flag'):
        raise PermissionDenied
    spam = Spam()

    if request.method == 'POST':
        review = Review.objects.get(pk=request.POST['review'])
        if 'del_review' in request.POST:
            log.info('SPAM: %s' % review.id)
            delete(request, request.POST['addon'], review.id)
            messages.success(request, 'Deleted that review.')
        elif 'del_user' in request.POST:
            user = review.user
            log.info('SPAMMER: %s deleted %s' %
                     (request.user.username, user.username))
            if not user.is_developer:
                Review.objects.filter(user=user).delete()
                user.anonymize()
            messages.success(request, 'Deleted that dirty spammer.')

        for reason in spam.reasons():
            spam.redis.srem(reason, review.id)
        return http.HttpResponseRedirect(request.path)

    buckets = {}
    for reason in spam.reasons():
        ids = spam.redis.smembers(reason)
        key = reason.split(':')[-1]
        buckets[key] = Review.objects.no_cache().filter(id__in=ids)
    reviews = dict((review.addon_id, review)
                   for bucket in buckets.values()
                   for review in bucket)
    for addon in Addon.objects.no_cache().filter(id__in=reviews):
        reviews[addon.id].addon = addon
    return render(request, 'reviews/spam.html',
                  dict(buckets=buckets, review_perms=dict(is_admin=True)))


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

    def get_addon_object(self):
        # When loading the add-on, pass a specific permission class - the
        # default from AddonViewSet is too restrictive, we are not modifying
        # the add-on itself so we don't need all the permission checks it does.
        return super(ReviewViewSet, self).get_addon_object(
            permission_classes=[AllowIfReviewedAndListed])

    def check_permissions(self, request):
        if 'addon_pk' in self.kwargs:
            # In addition to the regular permission checks that are made, we
            # need to verify that the add-on exists, is public and listed. Just
            # loading the addon should be enough to do that, since
            # AddonChildMixin implementation calls AddonViewSet.get_object().
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
            if 'addon_pk' in self.kwargs:
                qs = qs.filter(addon=self.get_addon_object())
            elif 'account_pk' in self.kwargs:
                qs = qs.filter(user=self.kwargs.get('account_pk'))
            else:
                # Don't allow listing reviews without filtering by add-on or
                # user.
                raise ParseError('Need an addon or user identifier')
        return qs

    def get_queryset(self):
        requested = self.request.GET.get('filter')

        # Add this as a property of the view, because we need to pass down the
        # information to the serializer to show/hide delete replies.
        self.should_access_deleted_reviews = (
            (requested == 'with_deleted' or self.action != 'list') and
            self.request.user.is_authenticated() and
            acl.action_allowed(self.request, 'Addons', 'Edit'))

        should_access_only_replies = (
            self.action == 'list' and self.kwargs.get('addon_pk'))

        if self.should_access_deleted_reviews:
            # For admins. When listing, we include deleted reviews but still
            # filter out out replies, because they'll be in the serializer
            # anyway. For other actions, we simply remove any filtering,
            # allowing them to access any review out of the box with no
            # extra parameter needed.
            if self.action == 'list':
                self.queryset = Review.unfiltered.filter(reply_to__isnull=True)
            else:
                self.queryset = Review.unfiltered.all()
        elif should_access_only_replies:
            # When listing add-on reviews, exclude replies, they'll be
            # included during serialization as children of the relevant
            # reviews instead.
            self.queryset = Review.without_replies.all()

        qs = super(ReviewViewSet, self).get_queryset()
        # The serializer needs user, reply and version, so use
        # prefetch_related() to avoid extra queries (avoid select_related() as
        # we need crazy joins already). Also avoid loading addon since we don't
        # need it, we already loaded it for permission checks through the pk
        # specified in the URL.
        return qs.defer('addon').prefetch_related('reply', 'user', 'version')

    @detail_route(
        methods=['post'], permission_classes=reply_permission_classes,
        serializer_class=reply_serializer_class)
    def reply(self, *args, **kwargs):
        # A reply is just like a regular post, except that we set the reply
        # FK to the current review object and only allow add-on authors/admins.
        # Call get_object() to trigger 404 if it does not exist.
        self.review_object = self.get_object()
        return self.create(*args, **kwargs)
