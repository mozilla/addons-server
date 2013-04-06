import datetime
import json

from django.conf import settings
from django.db.models import Q
from django.forms.formsets import formset_factory
from django.shortcuts import get_object_or_404, redirect
from django.utils.datastructures import MultiValueDictKeyError

import jingo
from tower import ugettext as _
from waffle.decorators import waffle_switch

import amo
from access import acl
from addons.models import Persona
from amo.decorators import json_view, post_required
from amo.urlresolvers import reverse
from amo.utils import paginate
from devhub.models import ActivityLog
from editors.views import reviewer_required
from zadmin.decorators import admin_required

import mkt.constants.reviewers as rvw

from . import forms
from .models import ThemeLock
from .views import context, queue_counts


@waffle_switch('mkt-themes')
@reviewer_required('persona')
def themes_queue(request):
    # By default, redirect back to the queue after a commit.
    request.session['theme_redirect_url'] = reverse(
        'reviewers.themes.queue_themes')

    return _themes_queue(request)


@waffle_switch('mkt-themes')
@admin_required(reviewers=True)
def themes_queue_flagged(request):
    # By default, redirect back to the queue after a commit.
    request.session['theme_redirect_url'] = reverse(
        'reviewers.themes.queue_flagged')

    return _themes_queue(request, flagged=True)


def _themes_queue(request, flagged=False):
    themes = _get_themes(request, request.amo_user, initial=True,
                         flagged=flagged)

    ThemeReviewFormset = formset_factory(forms.ThemeReviewForm)
    formset = ThemeReviewFormset(
        initial=[{'theme': theme.id} for theme in themes])

    more_url = reverse('reviewers.themes.more')
    if flagged:
        more_url = reverse('reviewers.themes.more_flagged')

    return jingo.render(request, 'reviewers/themes/queue.html', context(**{
        'actions': get_actions_json(),
        'formset': formset,
        'flagged': flagged,
        'max_locks': rvw.THEME_MAX_LOCKS,
        'more_url': more_url,
        'queue_counts': queue_counts(),
        'reject_reasons': rvw.THEME_REJECT_REASONS.items(),
        'reviewable': True,
        'theme_formsets': zip(themes, formset),
        'theme_count': len(themes),
    }))


def _get_themes(request, reviewer, initial=True, flagged=False):
    """Check out themes.

    :param initial: True if checking out synchronously, False otherwise.
                    Changes whether we return all of reviewer's themes or just
                    newly checked out ones.

    """
    status = amo.STATUS_REVIEW_PENDING if flagged else amo.STATUS_PENDING

    theme_locks = ThemeLock.objects.filter(reviewer=reviewer,
                                           theme__addon__status=status)
    theme_locks_count = theme_locks.count()

    # Calculate number of themes to check out.
    if initial:
        if theme_locks_count < rvw.THEME_INITIAL_LOCKS:
            # Check out themes from the pool if none or not enough checked out.
            wanted_locks = rvw.THEME_INITIAL_LOCKS - theme_locks_count
        else:
            # Update the expiry on currently checked-out themes.
            theme_locks.update(expiry=get_updated_expiry())
            return [theme_lock.theme for theme_lock in theme_locks]
    else:
        # Logic to not take over than the max number of locks.
        if theme_locks_count > rvw.THEME_MAX_LOCKS - rvw.THEME_INITIAL_LOCKS:
            # Take the max.
            wanted_locks = rvw.THEME_MAX_LOCKS - theme_locks_count
        else:
            wanted_locks = rvw.THEME_INITIAL_LOCKS

    themes = Persona.objects.no_cache().filter(addon__status=status,
                                               themelock=None)
    if not settings.ALLOW_SELF_REVIEWS and not acl.action_allowed(request,
                                                                  'Admin',
                                                                  '%'):
        themes = themes.exclude(addon__addonuser__user=reviewer)
    themes = list(themes[:wanted_locks])

    # Set a lock on the checked-out themes.
    expiry = get_updated_expiry()
    for theme in themes:
        ThemeLock.objects.create(theme=theme, reviewer=reviewer, expiry=expiry)

    # Empty pool? Go look for some expired locks.
    if not themes:
        expired_locks = ThemeLock.objects.filter(
            expiry__lte=datetime.datetime.now())[:rvw.THEME_INITIAL_LOCKS]
        # Steal expired locks.
        for theme_lock in expired_locks:
            theme_lock.reviewer = reviewer
            theme_lock.expiry = expiry
            theme_lock.save()
            themes = [theme_lock.theme for theme_lock in expired_locks]

    if initial:
        return [lock.theme for lock in theme_locks]
    else:
        return themes


@waffle_switch('mkt-themes')
@post_required
@reviewer_required('persona')
def themes_commit(request):
    reviewer = request.user.get_profile()
    ThemeReviewFormset = formset_factory(forms.ThemeReviewForm)
    formset = ThemeReviewFormset(request.POST)

    for form in formset:
        try:
            theme_lock = ThemeLock.objects.filter(
                theme_id=form.data[form.prefix + '-theme'],
                reviewer=reviewer)
        except MultiValueDictKeyError:
            # Address off-by-one error caused by management form.
            continue
        if theme_lock and form.is_valid():
            form.save()

    if 'theme_redirect_url' in request.session:
        return redirect(request.session['theme_redirect_url'])
    else:
        return redirect(reverse('reviewers.themes.queue_themes'))


@json_view
@admin_required(reviewers=True)
def themes_more_flagged(request):
    return themes_more(request, flagged=True)


@json_view
@reviewer_required('persona')
def themes_more(request, flagged=False):
    reviewer = request.user.get_profile()
    theme_locks_count = ThemeLock.uncached.filter(
        reviewer=reviewer, expiry__gte=datetime.datetime.now()).count()

    # Maximum number of locks.
    if theme_locks_count >= rvw.THEME_MAX_LOCKS:
        return {
            'themes': [],
            'message': _('You have reached the maximum number of Themes to '
                         'review at once. Please commit your outstanding '
                         'reviews.')
        }

    themes = _get_themes(request, reviewer, initial=False, flagged=flagged)

    # Create forms, which will need to be manipulated to fit with the currently
    # existing forms.
    ThemeReviewFormset = formset_factory(forms.ThemeReviewForm)
    formset = ThemeReviewFormset(
        initial=[{'theme': theme.id} for theme in themes])

    html = jingo.render(request, 'reviewers/themes/themes.html', {
        'theme_formsets': zip(themes, formset),
        'max_locks': rvw.THEME_MAX_LOCKS,
        'reviewable': True,
        'initial_count': theme_locks_count,
        'reject_reasons': rvw.THEME_REJECT_REASONS.items()
    }).content

    return {'html': html,
            'count': ThemeLock.objects.filter(reviewer=reviewer).count()}


@waffle_switch('mkt-themes')
@reviewer_required('persona')
def themes_single(request, slug):
    """
    Like a detail page, manually review a single theme if it is pending
    and isn't locked.
    """
    reviewer = request.user.get_profile()
    reviewable = True

    # Don't review an already reviewed theme.
    theme = get_object_or_404(Persona, addon__slug=slug)
    if theme.addon.status != amo.STATUS_PENDING:
        reviewable = False

    if (not settings.ALLOW_SELF_REVIEWS and
        not acl.action_allowed(request, 'Admin', '%') and
        theme.addon.has_author(request.amo_user)):
        reviewable = False

    # Don't review a locked theme (that's not locked to self).
    try:
        theme_lock = theme.themelock
        if (theme_lock.reviewer.id != reviewer.id and
            theme_lock.expiry > datetime.datetime.now()):
            reviewable = False
        elif (theme_lock.reviewer.id != reviewer.id and
              theme_lock.expiry < datetime.datetime.now()):
            # Steal expired lock.
            theme_lock.reviewer = reviewer,
            theme_lock.expiry = get_updated_expiry()
            theme_lock.save()
        else:
            # Update expiry.
            theme_lock.expiry = get_updated_expiry()
            theme_lock.save()
    except ThemeLock.DoesNotExist:
        # Create lock if not created.
        ThemeLock.objects.create(theme=theme, reviewer=reviewer,
                                 expiry=get_updated_expiry())

    ThemeReviewFormset = formset_factory(forms.ThemeReviewForm)
    formset = ThemeReviewFormset(initial=[{'theme': theme.id}])

    # Since we started the review on the single page, we want to return to the
    # single page rather than get shot back to the queue.
    request.session['theme_redirect_url'] = reverse('reviewers.themes.single',
                                                    args=[theme.addon.slug])

    return jingo.render(request, 'reviewers/themes/single.html', context(**{
        'formset': formset,
        'theme': theme,
        'theme_formsets': zip([theme], formset),
        'theme_reviews': paginate(request, ActivityLog.objects.filter(
            action=amo.LOG.THEME_REVIEW.id,
            _arguments__contains=theme.addon.id)),
        # Setting this to 0 makes sure more themes aren't loaded from more().
        'max_locks': 0,
        'actions': get_actions_json(),
        'theme_count': 1,
        'reviewable': reviewable,
        'reject_reasons': rvw.THEME_REJECT_REASONS.items(),
        'action_dict': rvw.REVIEW_ACTIONS,
    }))


@waffle_switch('mkt-themes')
@reviewer_required('persona')
def themes_logs(request):
    data = request.GET.copy()

    if not data.get('start') and not data.get('end'):
        today = datetime.date.today()
        data['start'] = datetime.date(today.year, today.month, 1)

    form = forms.ReviewAppLogForm(data)

    theme_logs = ActivityLog.objects.filter(action=amo.LOG.THEME_REVIEW.id)

    if form.is_valid():
        data = form.cleaned_data
        if data.get('start'):
            theme_logs = theme_logs.filter(created__gte=data['start'])
        if data.get('end'):
            theme_logs = theme_logs.filter(created__lt=data['end'])
        if data.get('search'):
            term = data['search']
            theme_logs = theme_logs.filter(
                Q(_details__icontains=term) |
                Q(user__display_name__icontains=term) |
                Q(user__username__icontains=term)).distinct()

    pager = paginate(request, theme_logs, 30)
    data = context(form=form, pager=pager, ACTION_DICT=rvw.REVIEW_ACTIONS,
                   REJECT_REASONS=rvw.THEME_REJECT_REASONS)
    return jingo.render(request, 'reviewers/themes/logs.html', data)


@waffle_switch('mkt-themes')
@reviewer_required('persona')
def themes_history(request, username):
    if not username:
        username = request.amo_user.username

    return jingo.render(request, 'reviewers/themes/history.html', context(**{
        'theme_reviews': paginate(request, ActivityLog.objects.filter(
            action=amo.LOG.THEME_REVIEW.id, user__username=username), 20),
        'user_history': True,
        'username': username,
        'reject_reasons': rvw.THEME_REJECT_REASONS.items(),
        'action_dict': rvw.REVIEW_ACTIONS,
    }))


def get_actions_json():
    return json.dumps({
        'moreinfo': rvw.ACTION_MOREINFO,
        'flag': rvw.ACTION_FLAG,
        'duplicate': rvw.ACTION_DUPLICATE,
        'reject': rvw.ACTION_REJECT,
        'approve': rvw.ACTION_APPROVE,
    })


def get_updated_expiry():
    return (datetime.datetime.now() +
            datetime.timedelta(minutes=rvw.THEME_LOCK_EXPIRY))
