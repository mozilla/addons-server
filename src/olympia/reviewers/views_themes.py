import datetime
import json

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.forms.formsets import formset_factory
from django.shortcuts import get_object_or_404, redirect
from django.utils.datastructures import MultiValueDictKeyError
from django.utils.translation import ugettext, ungettext

from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, Persona
from olympia.amo.decorators import json_view, post_required
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import paginate, render
from olympia.reviewers import forms
from olympia.reviewers.models import (
    RereviewQueueTheme,
    ReviewerScore,
    ThemeLock,
)
from olympia.reviewers.views import base_context as context

from .decorators import personas_reviewer_required


QUEUE_PER_PAGE = 100


@personas_reviewer_required
def themes_list(request, flagged=False, rereview=False):
    """Themes queue in list format."""
    themes = []
    if flagged:
        # TODO (ngoke): rename to STATUS_FLAGGED.
        themes = Addon.objects.filter(
            status=amo.STATUS_REVIEW_PENDING,
            type=amo.ADDON_PERSONA,
            persona__isnull=False,
        )
    elif rereview:
        themes = [
            rqt.theme.addon
            for rqt in RereviewQueueTheme.objects.select_related(
                'theme__addon'
            )
        ]
    else:
        themes = Addon.objects.filter(
            status=amo.STATUS_PENDING,
            type=amo.ADDON_PERSONA,
            persona__isnull=False,
        )

    search_form = forms.ThemeSearchForm(request.GET)
    per_page = request.GET.get('per_page', QUEUE_PER_PAGE)
    pager = paginate(request, themes, per_page)

    return render(
        request,
        'reviewers/themes/queue_list.html',
        context(
            **{
                'addons': pager.object_list,
                'flagged': flagged,
                'pager': pager,
                'rereview': rereview,
                'theme_search_form': search_form,
                'statuses': dict(
                    (k, unicode(v)) for k, v in amo.STATUS_CHOICES_API.items()
                ),
                'tab': (
                    'rereview_themes'
                    if rereview
                    else 'flagged_themes'
                    if flagged
                    else 'pending_themes'
                ),
            }
        ),
    )


def _themes_queue(request, flagged=False, rereview=False):
    """Themes queue in interactive format."""
    themes = _get_themes(
        request, request.user, flagged=flagged, rereview=rereview
    )

    ThemeReviewFormset = formset_factory(forms.ThemeReviewForm)
    formset = ThemeReviewFormset(
        initial=[
            {'theme': _rereview_to_theme(rereview, theme).id}
            for theme in themes
        ]
    )

    return render(
        request,
        'reviewers/themes/queue.html',
        context(
            **{
                'actions': get_actions_json(),
                'formset': formset,
                'flagged': flagged,
                'reject_reasons': amo.THEME_REJECT_REASONS,
                'rereview': rereview,
                'reviewable': True,
                'theme_formsets': zip(themes, formset),
                'theme_count': len(themes),
                'tab': (
                    'flagged'
                    if flagged
                    else 'rereview'
                    if rereview
                    else 'pending'
                ),
            }
        ),
    )


def _get_themes(request, reviewer, flagged=False, rereview=False):
    """Check out themes.

    :param flagged: Flagged themes (amo.STATUS_REVIEW_PENDING)
    :param rereview: Re-uploaded themes (RereviewQueueTheme)

    """
    num = 0
    themes = []
    locks = []

    status = (
        amo.STATUS_REVIEW_PENDING
        if flagged
        else amo.STATUS_PUBLIC
        if rereview
        else amo.STATUS_PENDING
    )

    if rereview:
        # Rereview themes.
        num, themes, locks = _get_rereview_themes(reviewer)
    else:
        # Pending and flagged themes.
        locks = ThemeLock.objects.filter(
            reviewer=reviewer, theme__addon__status=status
        )
        num, themes = _calc_num_themes_checkout(locks)
        if themes:
            return themes
        themes = Persona.objects.filter(addon__status=status, themelock=None)

    # Don't allow self-reviews.
    if not settings.ALLOW_SELF_REVIEWS and not acl.action_allowed(
        request, amo.permissions.REVIEWS_ADMIN
    ):
        if rereview:
            themes = themes.exclude(theme__addon__addonuser__user=reviewer)
        else:
            themes = themes.exclude(addon__addonuser__user=reviewer)

    # Check out themes by setting lock.
    themes = list(themes)[:num]
    expiry = get_updated_expiry()
    for theme in themes:
        ThemeLock.objects.create(
            theme=_rereview_to_theme(rereview, theme),
            reviewer=reviewer,
            expiry=expiry,
        )

    # Empty pool? Go look for some expired locks.
    if not themes:
        expired_locks = ThemeLock.objects.filter(
            expiry__lte=datetime.datetime.now(), theme__addon__status=status
        )[: amo.THEME_INITIAL_LOCKS]
        # Steal expired locks.
        for lock in expired_locks:
            lock.reviewer = reviewer
            lock.expiry = expiry
            lock.save()
        if expired_locks:
            locks = expired_locks

    if rereview:
        return RereviewQueueTheme.objects.filter(
            theme__themelock__reviewer=reviewer
        ).exclude(theme__addon__status=amo.STATUS_REJECTED)

    # New theme locks may have been created, grab all reviewer's themes again.
    return [lock.theme for lock in locks]


@json_view
@personas_reviewer_required
def themes_search(request):
    search_form = forms.ThemeSearchForm(request.GET)
    if search_form.is_valid():
        q = search_form.cleaned_data['q']
        rereview = search_form.cleaned_data['queue_type'] == 'rereview'
        flagged = search_form.cleaned_data['queue_type'] == 'flagged'

        # ES query on name.
        themes = Addon.search().filter(type=amo.ADDON_PERSONA)
        if rereview:
            themes = themes.filter(has_theme_rereview=True)
        else:
            themes = themes.filter(
                status=(
                    amo.STATUS_REVIEW_PENDING
                    if flagged
                    else amo.STATUS_PENDING
                ),
                has_theme_rereview=False,
            )
        themes = themes.filter_query_string(q)[:100]

        now = datetime.datetime.now()
        reviewers = []
        for theme in themes:
            try:
                themelock = theme.persona.themelock
                if themelock.expiry > now:
                    reviewers.append(themelock.reviewer.email)
                else:
                    reviewers.append('')
            except ObjectDoesNotExist:
                reviewers.append('')

        themes = list(themes.values_dict('name', 'slug', 'status'))

        for theme, reviewer in zip(themes, reviewers):
            # Collapse single value fields from a list.
            theme['id'] = theme['id']
            theme['slug'] = theme['slug']
            theme['status'] = theme['status']
            # Dehydrate.
            theme['reviewer'] = reviewer

        return {'objects': themes, 'meta': {'total_count': len(themes)}}


@personas_reviewer_required
def themes_queue(request):
    # By default, redirect back to the queue after a commit.
    request.session['theme_redirect_url'] = reverse(
        'reviewers.themes.queue_themes'
    )

    return _themes_queue(request)


@personas_reviewer_required
def themes_queue_flagged(request):
    # By default, redirect back to the queue after a commit.
    request.session['theme_redirect_url'] = reverse(
        'reviewers.themes.queue_flagged'
    )

    return _themes_queue(request, flagged=True)


@personas_reviewer_required
def themes_queue_rereview(request):
    # By default, redirect back to the queue after a commit.
    request.session['theme_redirect_url'] = reverse(
        'reviewers.themes.queue_rereview'
    )

    return _themes_queue(request, rereview=True)


def _rereview_to_theme(rereview, theme):
    """
    Follows foreign key of RereviewQueueTheme object to theme if in rereview
    queue.
    """
    if rereview:
        return theme.theme
    return theme


def _calc_num_themes_checkout(locks):
    """
    Calculate number of themes to check out based on how many themes user
    currently has checked out.
    """
    current_num = locks.count()
    if current_num < amo.THEME_INITIAL_LOCKS:
        # Check out themes from the pool if none or not enough checked out.
        return amo.THEME_INITIAL_LOCKS - current_num, []
    else:
        # Update the expiry on currently checked-out themes.
        locks.update(expiry=get_updated_expiry())
        return 0, [lock.theme for lock in locks]


def _get_rereview_themes(reviewer):
    """Check out re-uploaded themes."""
    locks = (
        ThemeLock.objects.select_related()
        .filter(reviewer=reviewer, theme__rereviewqueuetheme__isnull=False)
        .exclude(theme__addon__status=amo.STATUS_REJECTED)
    )

    num, updated_locks = _calc_num_themes_checkout(locks)
    if updated_locks:
        locks = updated_locks

    themes = RereviewQueueTheme.objects.filter(
        theme__addon__isnull=False, theme__themelock=None
    ).exclude(theme__addon__status=amo.STATUS_REJECTED)
    return num, themes, locks


@post_required
@personas_reviewer_required
def themes_commit(request):
    ThemeReviewFormset = formset_factory(forms.ThemeReviewForm)
    formset = ThemeReviewFormset(request.POST)

    scores = []
    for form in formset:
        try:
            lock = ThemeLock.objects.filter(
                theme_id=form.data[form.prefix + '-theme'],
                reviewer=request.user,
            )
        except MultiValueDictKeyError:
            # Address off-by-one error caused by management form.
            continue
        if lock and form.is_valid():
            scores.append(form.save())

    # Success message.
    points = sum(scores)
    success = ungettext(
        # L10n: {0} is the number of reviews. {1} is the points just earned.
        # L10n: {2} is the total number of points the reviewer has overall.
        '{0} theme review successfully processed (+{1} points, {2} total).',
        '{0} theme reviews successfully processed (+{1} points, {2} total).',
        len(scores),
    ).format(len(scores), points, ReviewerScore.get_total(request.user))
    amo.messages.success(request, success)

    if 'theme_redirect_url' in request.session:
        return redirect(request.session['theme_redirect_url'])
    else:
        return redirect(reverse('reviewers.themes.queue_themes'))


@personas_reviewer_required
def release_locks(request):
    ThemeLock.objects.filter(reviewer=request.user).delete()
    amo.messages.success(
        request,
        ugettext(
            'Your theme locks have successfully been released. '
            'Other reviewers may now review those released themes. '
            'You may have to refresh the page to see the changes reflected in '
            'the table below.'
        ),
    )
    return redirect(reverse('reviewers.themes.list'))


@personas_reviewer_required
def themes_single(request, slug):
    """
    Like a detail page, manually review a single theme if it is pending
    and isn't locked.
    """
    reviewer = request.user
    reviewable = True

    # Don't review an already reviewed theme.
    theme = get_object_or_404(Persona, addon__slug=slug)
    if (
        theme.addon.status != amo.STATUS_PENDING
        and not theme.rereviewqueuetheme_set.all()
    ):
        reviewable = False

    if (
        not settings.ALLOW_SELF_REVIEWS
        and not acl.action_allowed(request, amo.permissions.REVIEWS_ADMIN)
        and theme.addon.has_author(request.user)
    ):
        reviewable = False
    else:
        # Don't review a locked theme (that's not locked to self).
        try:
            lock = theme.themelock
            if (
                lock.reviewer.id != reviewer.id
                and lock.expiry > datetime.datetime.now()
            ):
                reviewable = False
            elif (
                lock.reviewer.id != reviewer.id
                and lock.expiry < datetime.datetime.now()
            ):
                # Steal expired lock.
                lock.reviewer = reviewer
                lock.expiry = get_updated_expiry()
                lock.save()
            else:
                # Update expiry.
                lock.expiry = get_updated_expiry()
                lock.save()
        except ThemeLock.DoesNotExist:
            # Create lock if not created.
            ThemeLock.objects.create(
                theme=theme, reviewer=reviewer, expiry=get_updated_expiry()
            )

    ThemeReviewFormset = formset_factory(forms.ThemeReviewForm)
    formset = ThemeReviewFormset(initial=[{'theme': theme.id}])

    # Since we started the review on the single page, we want to return to the
    # single page rather than get shot back to the queue.
    request.session['theme_redirect_url'] = reverse(
        'reviewers.themes.single', args=[theme.addon.slug]
    )

    rereview = (
        theme.rereviewqueuetheme_set.all()[0]
        if theme.rereviewqueuetheme_set.exists()
        else None
    )
    return render(
        request,
        'reviewers/themes/single.html',
        context(
            **{
                'formset': formset,
                'theme': rereview if rereview else theme,
                'theme_formsets': zip(
                    [rereview if rereview else theme], formset
                ),
                'theme_reviews': paginate(
                    request,
                    ActivityLog.objects.filter(
                        action=amo.LOG.THEME_REVIEW.id,
                        _arguments__contains=theme.addon.id,
                    ),
                ),
                'actions': get_actions_json(),
                'theme_count': 1,
                'rereview': rereview,
                'reviewable': reviewable,
                'reject_reasons': amo.THEME_REJECT_REASONS,
                'action_dict': amo.REVIEW_ACTIONS,
                'tab': (
                    'flagged'
                    if theme.addon.status == amo.STATUS_REVIEW_PENDING
                    else 'rereview'
                    if rereview
                    else 'pending'
                ),
            }
        ),
    )


@personas_reviewer_required
def themes_logs(request):
    data = request.GET.copy()

    if not data.get('start') and not data.get('end'):
        today = datetime.date.today()
        data['start'] = datetime.date(today.year, today.month, 1)

    form = forms.ReviewThemeLogForm(data)

    theme_logs = ActivityLog.objects.filter(action=amo.LOG.THEME_REVIEW.id)

    if form.is_valid():
        data = form.cleaned_data
        if data.get('start'):
            theme_logs = theme_logs.filter(created__gte=data['start'])
        if data.get('end'):
            theme_logs = theme_logs.filter(created__lte=data['end'])
        if data.get('search'):
            term = data['search']
            theme_logs = theme_logs.filter(
                Q(_details__icontains=term)
                | Q(user__display_name__icontains=term)
                | Q(user__username__icontains=term)
            ).distinct()

    pager = paginate(request, theme_logs, 30)
    data = context(
        form=form,
        pager=pager,
        ACTION_DICT=amo.REVIEW_ACTIONS,
        REJECT_REASONS=amo.THEME_REJECT_REASONS,
        tab='themes',
    )
    return render(request, 'reviewers/themes/logs.html', data)


@personas_reviewer_required
def deleted_themes(request):
    data = request.GET.copy()
    deleted = Addon.unfiltered.filter(
        type=amo.ADDON_PERSONA, status=amo.STATUS_DELETED
    )

    if not data.get('start') and not data.get('end'):
        today = datetime.date.today()
        data['start'] = datetime.date(today.year, today.month, 1)

    form = forms.DeletedThemeLogForm(data)
    if form.is_valid():
        data = form.cleaned_data
        if data.get('start'):
            deleted = deleted.filter(modified__gte=data['start'])
        if data.get('end'):
            deleted = deleted.filter(modified__lte=data['end'])
        if data.get('search'):
            term = data['search']
            deleted = deleted.filter(Q(name__localized_string__icontains=term))

    return render(
        request,
        'reviewers/themes/deleted.html',
        {
            'form': form,
            'pager': paginate(request, deleted.order_by('-modified'), 30),
            'tab': 'deleted',
        },
    )


@personas_reviewer_required
def themes_history(request, username):
    if not username:
        username = request.user.username

    return render(
        request,
        'reviewers/themes/history.html',
        context(
            **{
                'theme_reviews': paginate(
                    request,
                    ActivityLog.objects.filter(
                        action=amo.LOG.THEME_REVIEW.id, user__username=username
                    ),
                    20,
                ),
                'user_history': True,
                'username': username,
                'reject_reasons': amo.THEME_REJECT_REASONS,
                'action_dict': amo.REVIEW_ACTIONS,
            }
        ),
    )


def get_actions_json():
    return json.dumps(
        {
            'moreinfo': amo.ACTION_MOREINFO,
            'flag': amo.ACTION_FLAG,
            'duplicate': amo.ACTION_DUPLICATE,
            'reject': amo.ACTION_REJECT,
            'approve': amo.ACTION_APPROVE,
        }
    )


def get_updated_expiry():
    return datetime.datetime.now() + datetime.timedelta(
        minutes=amo.THEME_LOCK_EXPIRY
    )
