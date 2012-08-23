import datetime
import json
import sys
import traceback

from django.conf import settings
from django.db.models import Q
from django.shortcuts import redirect

import jingo
from tower import ugettext as _
import requests

import amo
from abuse.models import AbuseReport
from access import acl
from addons.decorators import addon_view
from addons.models import Version
from amo import messages
from amo.decorators import json_view, permission_required
from amo.urlresolvers import reverse
from amo.utils import escape_all
from amo.utils import paginate
from editors.forms import MOTDForm
from editors.models import EditorSubscription, EscalationQueue
from editors.views import reviewer_required
from mkt.developers.models import ActivityLog
from mkt.webapps.models import Webapp
from reviews.forms import ReviewFlagFormSet
from reviews.models import Review, ReviewFlag
from zadmin.models import get_config, set_config
from . import forms
from .models import AppCannedResponse, RereviewQueue


QUEUE_PER_PAGE = 100


@reviewer_required
def home(request):
    durations = (('new', _('New Apps (Under 5 days)')),
                 ('med', _('Passable (5 to 10 days)')),
                 ('old', _('Overdue (Over 10 days)')))

    progress, percentage = _progress()

    data = context(
        reviews_total=ActivityLog.objects.total_reviews(webapp=True)[:5],
        reviews_monthly=ActivityLog.objects.monthly_reviews(webapp=True)[:5],
        #new_editors=EventLog.new_editors(),  # Bug 747035
        #eventlog=ActivityLog.objects.editor_events()[:6],  # Bug 746755
        progress=progress,
        percentage=percentage,
        durations=durations
    )
    return jingo.render(request, 'reviewers/home.html', data)


def queue_counts():
    excluded_ids = EscalationQueue.uncached.values_list('addon', flat=True)

    counts = {
        'pending': Webapp.uncached.exclude(id__in=excluded_ids)
                                  .filter(status=amo.WEBAPPS_UNREVIEWED_STATUS,
                                          disabled_by_user=False)
                                  .count(),
        'rereview': RereviewQueue.uncached
                                 .exclude(addon__in=excluded_ids)
                                 .filter(addon__disabled_by_user=False)
                                 .count(),
        'escalated': EscalationQueue.uncached
                                    .filter(addon__disabled_by_user=False)
                                    .count(),
        'moderated': Review.uncached.filter(reviewflag__isnull=False,
                                            editorreview=True,
                                            addon__type=amo.ADDON_WEBAPP)
                                    .count(),
    }
    rv = {}
    if isinstance(type, basestring):
        return counts[type]
    for k, v in counts.items():
        if not isinstance(type, list) or k in type:
            rv[k] = v
    return rv


def _progress():
    """Returns unreviewed apps progress.

    Return the number of apps still unreviewed for a given period of time and
    the percentage.
    """

    days_ago = lambda n: datetime.datetime.now() - datetime.timedelta(days=n)
    excluded_ids = EscalationQueue.uncached.values_list('addon', flat=True)
    qs = (Webapp.uncached.exclude(id__in=excluded_ids)
                         .filter(status=amo.WEBAPPS_UNREVIEWED_STATUS,
                                 disabled_by_user=False))
    progress = {
        'new': qs.filter(created__gt=days_ago(5)).count(),
        'med': qs.filter(created__range=(days_ago(10), days_ago(5))).count(),
        'old': qs.filter(created__lt=days_ago(10)).count(),
        'week': qs.filter(created__gte=days_ago(7)).count(),
    }

    # Return the percent of (p)rogress out of (t)otal.
    pct = lambda p, t: (p / float(t)) * 100 if p > 0 else 0

    percentage = {}
    total = progress['new'] + progress['med'] + progress['old']
    percentage = {}
    for duration in ('new', 'med', 'old'):
        percentage[duration] = pct(progress[duration], total)

    return (progress, percentage)


def context(**kw):
    ctx = dict(motd=get_config('mkt_reviewers_motd'),
               queue_counts=queue_counts())
    ctx.update(kw)
    return ctx


def _review(request, addon):
    version = addon.latest_version

    if (not settings.DEBUG and
        addon.authors.filter(user=request.user).exists()):
        messages.warning(request, _('Self-reviews are not allowed.'))
        return redirect(reverse('reviewers.home'))

    form = forms.get_review_form(request.POST or None, request=request,
                                 addon=addon, version=version)
    queue_type = form.helper.review_type
    redirect_url = reverse('reviewers.apps.queue_%s' % queue_type)
    is_admin = acl.action_allowed(request, 'Addons', 'Edit')

    if request.method == 'POST' and form.is_valid():
        form.helper.process()
        if form.cleaned_data.get('notify'):
            EditorSubscription.objects.get_or_create(user=request.amo_user,
                                                     addon=addon)
        if form.cleaned_data.get('adminflag') and is_admin:
            addon.update(admin_review=False)
        messages.success(request, _('Review successfully processed.'))
        return redirect(redirect_url)

    canned = AppCannedResponse.objects.all()
    actions = form.helper.actions.items()

    statuses = [amo.STATUS_PUBLIC, amo.STATUS_LITE,
                amo.STATUS_LITE_AND_NOMINATED]

    try:
        show_diff = (addon.versions.exclude(id=version.id)
                                   .filter(files__isnull=False,
                                       created__lt=version.created,
                                       files__status__in=statuses)
                                   .latest())
    except Version.DoesNotExist:
        show_diff = None

    # The actions we should show a minimal form from.
    actions_minimal = [k for (k, a) in actions if not a.get('minimal')]

    # We only allow the user to check/uncheck files for "pending"
    allow_unchecking_files = form.helper.review_type == "pending"

    versions = (Version.objects.filter(addon=addon)
                               .exclude(files__status=amo.STATUS_BETA)
                               .order_by('-created')
                               .transform(Version.transformer_activity)
                               .transform(Version.transformer))

    pager = paginate(request, versions, 10)

    num_pages = pager.paginator.num_pages
    count = pager.paginator.count

    ctx = context(version=version, product=addon, pager=pager,
                  num_pages=num_pages, count=count,
                  flags=Review.objects.filter(addon=addon, flag=True),
                  form=form, canned=canned, is_admin=is_admin,
                  status_types=amo.STATUS_CHOICES, show_diff=show_diff,
                  allow_unchecking_files=allow_unchecking_files,
                  actions=actions, actions_minimal=actions_minimal,
                  tab=queue_type)

    return jingo.render(request, 'reviewers/review.html', ctx)


@permission_required('Apps', 'Review')
@addon_view
def app_review(request, addon):
    return _review(request, addon)


def _queue(request, qs, tab, pager_processor=None):
    per_page = request.GET.get('per_page', QUEUE_PER_PAGE)
    pager = paginate(request, qs, per_page)

    if pager_processor:
        addons = pager_processor(pager)
    else:
        addons = pager.object_list

    return jingo.render(request, 'reviewers/queue.html', context(**{
        'addons': addons,
        'pager': pager,
        'tab': tab,
    }))


@permission_required('Apps', 'Review')
def queue_apps(request):
    excluded_ids = EscalationQueue.uncached.values_list('addon', flat=True)
    qs = (Webapp.uncached.filter(status=amo.WEBAPPS_UNREVIEWED_STATUS)
                         .exclude(id__in=excluded_ids)
                         .filter(disabled_by_user=False)
                         .order_by('created'))
    return _queue(request, qs, 'pending')


@permission_required('Apps', 'Review')
def queue_rereview(request):
    excluded_ids = EscalationQueue.uncached.values_list('addon', flat=True)
    qs = (RereviewQueue.uncached
                       .exclude(addon__in=excluded_ids)
                       .filter(addon__disabled_by_user=False)
                       .order_by('created'))
    return _queue(request, qs, 'rereview',
                  lambda p: [r.addon for r in p.object_list])


@permission_required('Apps', 'ReviewEscalated')
def queue_escalated(request):
    qs = (EscalationQueue.uncached.filter(addon__disabled_by_user=False)
                         .order_by('created'))
    return _queue(request, qs, 'escalated',
                  lambda p: [r.addon for r in p.object_list])


@permission_required('Apps', 'Review')
def queue_moderated(request):
    rf = (Review.uncached.exclude(
                             Q(addon__isnull=True) |
                             Q(reviewflag__isnull=True))
                         .filter(addon__type=amo.ADDON_WEBAPP,
                                 editorreview=True)
                         .order_by('reviewflag__created'))

    page = paginate(request, rf, per_page=20)
    flags = dict(ReviewFlag.FLAGS)
    reviews_formset = ReviewFlagFormSet(request.POST or None,
                                        queryset=page.object_list)

    if reviews_formset.is_valid():
        reviews_formset.save()
        return redirect(reverse('reviewers.apps.queue_moderated'))

    return jingo.render(request, 'reviewers/queue.html',
                        context(reviews_formset=reviews_formset,
                                tab='moderated', page=page, flags=flags))


@permission_required('Apps', 'Review')
def logs(request):
    data = request.GET.copy()

    if not data.get('start') and not data.get('end'):
        today = datetime.date.today()
        data['start'] = datetime.date(today.year, today.month, 1)

    form = forms.ReviewAppLogForm(data)

    approvals = ActivityLog.objects.review_queue(webapp=True)

    if form.is_valid():
        data = form.cleaned_data
        if data.get('start'):
            approvals = approvals.filter(created__gte=data['start'])
        if data.get('end'):
            approvals = approvals.filter(created__lt=data['end'])
        if data.get('search'):
            term = data['search']
            approvals = approvals.filter(
                    Q(commentlog__comments__icontains=term) |
                    Q(applog__addon__name__localized_string__icontains=term) |
                    Q(applog__addon__app_slug__icontains=term) |
                    Q(user__display_name__icontains=term) |
                    Q(user__username__icontains=term)).distinct()

    pager = amo.utils.paginate(request, approvals, 50)
    data = context(form=form, pager=pager, ACTION_DICT=amo.LOG_BY_ID)
    return jingo.render(request, 'reviewers/logs.html', data)


@reviewer_required
def motd(request):
    form = None
    motd = get_config('mkt_reviewers_motd')
    if acl.action_allowed(request, 'AppReviewerMOTD', 'Edit'):
        form = MOTDForm(request.POST or None, initial={'motd': motd})
    if form and request.method == 'POST' and form.is_valid():
            set_config(u'mkt_reviewers_motd', form.cleaned_data['motd'])
            return redirect(reverse('reviewers.apps.motd'))
    data = context(form=form)
    return jingo.render(request, 'reviewers/motd.html', data)


@permission_required('Apps', 'Review')
@addon_view
@json_view
def app_view_manifest(request, addon):
    content, headers = '', {}
    if addon.manifest_url:
        try:
            req = requests.get(addon.manifest_url, verify=False)
            content, headers = req.content, req.headers
        except Exception:
            content = ''.join(traceback.format_exception(*sys.exc_info()))

        try:
            # Reindent the JSON.
            content = json.dumps(json.loads(content), indent=4)
        except:
            # If it's not valid JSON, just return the content as is.
            pass
    return escape_all({'content': content, 'headers': headers})


@permission_required('Apps', 'Review')
@addon_view
def app_abuse(request, addon):
    reports = AbuseReport.objects.filter(addon=addon).order_by('-created')
    total = reports.count()
    reports = amo.utils.paginate(request, reports, count=total)
    return jingo.render(request, 'reviewers/abuse.html',
                        context(addon=addon, reports=reports, total=total))
