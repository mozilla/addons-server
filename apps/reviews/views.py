from django import http
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template import Context, loader

import commonware.log
import jingo
from tower import ugettext as _
from mobility.decorators import mobile_template
from waffle.decorators import waffle_switch

import amo
from amo import messages
from amo.decorators import (json_view, login_required, post_required,
                            restricted_content)
from amo.helpers import absolutify, shared_url
import amo.utils
from access import acl
from addons.decorators import addon_view_factory, has_purchased
from addons.models import Addon

from .helpers import user_can_delete_review
from .models import Review, ReviewFlag, GroupedRating, Spam
from . import forms

import HTMLParser
import json
import requests

log = commonware.log.getLogger('z.reviews')
addon_view = addon_view_factory(qs=Addon.objects.valid)


def send_mail(template, subject, emails, context, perm_setting):
    template = loader.get_template(template)
    amo.utils.send_mail(subject, template.render(Context(context,
                                                         autoescape=False)),
                        recipient_list=emails, perm_setting=perm_setting)


@addon_view
@mobile_template('reviews/{mobile/}review_list.html')
def review_list(request, addon, review_id=None, user_id=None, template=None):
    q = (Review.objects.valid().filter(addon=addon)
         .order_by('-created'))

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
        q = q.filter(pk=review_id)
    elif user_id is not None:
        ctx['page'] = 'user'
        q = q.filter(user=user_id)
        if not q:
            raise http.Http404()
    else:
        ctx['page'] = 'list'
        q = q.filter(is_latest=True)

    ctx['reviews'] = reviews = amo.utils.paginate(request, q)
    ctx['replies'] = Review.get_replies(reviews.object_list)
    if request.user.is_authenticated():
        ctx['review_perms'] = {
            'is_admin': acl.action_allowed(request, 'Addons', 'Edit'),
            'is_editor': acl.check_reviewer(request),
            'is_author': acl.check_addon_ownership(request, addon, viewer=True,
                                                   dev=True, support=True),
        }
        ctx['flags'] = get_flags(request, reviews.object_list)
    else:
        ctx['review_perms'] = {}
    return jingo.render(request, template, ctx)


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
def translate(request, addon, review_id, language):
    """
    Use the Google Translate API for ajax, redirect to Google Translate for
    non ajax calls.
    """
    review = get_object_or_404(Review.objects, pk=review_id, addon=addon)
    if '-' in language:
        language = language.split('-')[0]

    if request.is_ajax():
        title, r = _retrieve_translation(review.title, language)
        body, r = _retrieve_translation(review.body, language)
        return http.HttpResponse(json.dumps({'title': title, 'body': body}),
                                 status=r.status_code)
    else:
        return redirect(settings.GOOGLE_TRANSLATE_REDIRECT_URL.format(
            lang=language, text=review.body))


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
             (request.amo_user.name, review_id, review.user.name, review.title,
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
                 defaults=dict(user=request.amo_user))
        reply, new = Review.objects.get_or_create(**d)
        for key, val in _review_details(request, addon, form).items():
            setattr(reply, key, val)
        reply.save()
        action = 'New' if new else 'Edited'
        log.debug('%s reply to %s: %s' % (action, review_id, reply.id))

        if new:
            reply_url = shared_url('reviews.detail', addon, review.id,
                                   add_prefix=False)
            data = {'name': addon.name,
                    'reply_title': reply.title,
                    'reply': reply.body,
                    'reply_url': absolutify(reply_url)}
            emails = [review.user.email]
            sub = u'Mozilla Add-on Developer Reply: %s' % addon.name
            send_mail('reviews/emails/reply_review.ltxt',
                      sub, emails, Context(data), 'reply')

        return redirect(shared_url('reviews.detail', addon, review_id))
    ctx = dict(review=review, form=form, addon=addon)
    return jingo.render(request, 'reviews/reply.html', ctx)


@addon_view
@mobile_template('reviews/{mobile/}add.html')
@login_required
@restricted_content
@has_purchased
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

        reply_url = shared_url('reviews.reply', addon, review.id,
                               add_prefix=False)
        data = {'name': addon.name,
                'rating': '%s out of 5 stars' % details['rating'],
                'review': details['body'],
                'reply_url': absolutify(reply_url)}

        emails = [a.email for a in addon.authors.all()]
        send_mail('reviews/emails/add_review.ltxt',
                  u'Mozilla Add-on User Review: %s' % addon.name,
                  emails, Context(data), 'new_review')

        return redirect(shared_url('reviews.list', addon))
    return jingo.render(request, template, dict(addon=addon, form=form))


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
        return http.HttpResponse()
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
                     (request.amo_user.username, user.username))
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
    reviews = dict((review.addon_id, review) for bucket in buckets.values()
                                             for review in bucket)
    for addon in Addon.objects.no_cache().filter(id__in=reviews):
        reviews[addon.id].addon = addon
    return jingo.render(request, 'reviews/spam.html',
                        dict(buckets=buckets,
                             review_perms=dict(is_admin=True)))
