from datetime import date, datetime, timedelta
import functools
import json
import time

from django import http
from django.conf import settings
from django.core.cache import cache
from django.shortcuts import redirect, get_object_or_404
from django.utils.datastructures import SortedDict
from django.views.decorators.cache import never_cache

import jingo
from tower import ugettext as _

import amo
from access import acl
from amo.decorators import login_required, json_view, post_required
from addons.models import Version
from amo.utils import paginate
from amo.urlresolvers import reverse
from devhub.models import ActivityLog
from editors import forms
from editors.models import (EditorSubscription, ViewPendingQueue,
                            ViewFullReviewQueue, ViewPreliminaryQueue,
                            EventLog, CannedResponse, PerformanceGraph)
from editors.helpers import (ViewPendingQueueTable, ViewFullReviewQueueTable,
                             ViewPreliminaryQueueTable)
from files.models import Approval
from reviews.forms import ReviewFlagFormSet
from reviews.models import Review, ReviewFlag
from users.models import UserProfile
from zadmin.models import get_config, set_config


def editor_required(func):
    """Requires the user to be logged in as an editor or admin."""
    @functools.wraps(func)
    @login_required
    def wrapper(request, *args, **kw):
        if acl.action_allowed(request, 'Editors', '%'):
            return func(request, *args, **kw)
        else:
            return http.HttpResponseForbidden()
    return wrapper


def context(**kw):
    ctx = dict(motd=get_config('editors_review_motd'),
               queue_counts=_queue_counts())
    ctx.update(kw)
    return ctx


@editor_required
def eventlog(request):
    form = forms.EventLogForm(request.GET)
    eventlog = ActivityLog.objects.editor_events()

    if form.is_valid():
        if form.cleaned_data['start']:
            eventlog = eventlog.filter(created__gte=form.cleaned_data['start'])
        if form.cleaned_data['end']:
            eventlog = eventlog.filter(created__lt=form.cleaned_data['end'])
        if form.cleaned_data['filter']:
            eventlog = eventlog.filter(action=form.cleaned_data['filter'].id)

    pager = amo.utils.paginate(request, eventlog, 50)

    data = context(form=form, pager=pager)
    return jingo.render(request, 'editors/eventlog.html', data)


@editor_required
def eventlog_detail(request, id):
    log = get_object_or_404(ActivityLog.objects.editor_events(), pk=id)
    data = context(log=log)
    return jingo.render(request, 'editors/eventlog_detail.html', data)


@editor_required
def home(request):
    durations = (('new', _('New Add-ons (Under 5 days)')),
                 ('med', _('Passable (5 to 10 days)')),
                 ('old', _('Overdue (Over 10 days)')))

    progress, percentage = _editor_progress()

    data = context(reviews_total=ActivityLog.objects.total_reviews()[:5],
                   reviews_monthly=ActivityLog.objects.monthly_reviews()[:5],
                   new_editors=EventLog.new_editors(),
                   eventlog=ActivityLog.objects.editor_events()[:6],
                   progress=progress, percentage=percentage,
                   durations=durations)

    return jingo.render(request, 'editors/home.html', data)


def _editor_progress():
    """Return the progress (number of add-ons still unreviewed for a given
       period of time) and the percentage (out of all add-ons of that type)."""

    types = ['nominated', 'prelim', 'pending']
    progress = {'new': _queue_counts(types, days_max=4),
                'med': _queue_counts(types, days_min=5, days_max=10),
                'old': _queue_counts(types, days_min=11),
                'week': _queue_counts(types, days_max=7)}

    # Return the percent of (p)rogress out of (t)otal.
    pct = lambda p, t: (p / float(t)) * 100 if p > 0 else 0

    percentage = {}
    for t in types:
        total = progress['new'][t] + progress['med'][t] + progress['old'][t]
        percentage[t] = {}
        for duration in ('new', 'med', 'old'):
            percentage[t][duration] = pct(progress[duration][t], total)

    return (progress, percentage)


@editor_required
def performance(request, user_id=False):
    user = request.amo_user
    editors = _recent_editors()

    is_admin = acl.action_allowed(request, 'Admin', '%')

    if is_admin and user_id:
        user_new = UserProfile.objects.filter(pk=user_id)
        if user_new.exists():
            user = user_new.all()[0]

    monthly_data = _performanceByMonth(user.id)
    performance_total = _performance_total(monthly_data)

    data = context(monthly_data=json.dumps(monthly_data),
                   performance_month=performance_total['month'],
                   performance_year=performance_total['year'],
                   editors=editors, current_user=user, is_admin=is_admin,
                   is_user=(request.amo_user.id == user.id))

    return jingo.render(request, 'editors/performance.html', data)


def _recent_editors(days=90):
    since_date = datetime.now() - timedelta(days=days)
    editors = (UserProfile.objects
                          .filter(activitylog__action__in=amo.LOG_REVIEW_QUEUE,
                                  activitylog__created__gt=since_date)
                          .order_by('display_name')
                          .distinct())
    return editors


def _performance_total(data):
    # TODO(gkoberger): Fix this so it's the past X, rather than this X to date.
    # (ex: March 15-April 15, not April 1 - April 15)
    total_yr = dict(usercount=0, teamamt=0, teamcount=0, teamavg=0)
    total_month = dict(usercount=0, teamamt=0, teamcount=0, teamavg=0)
    current_year = datetime.now().year

    for k, val in data.items():
        if k.startswith(str(current_year)):
            total_yr['usercount'] = total_yr['usercount'] + val['usercount']
            total_yr['teamamt'] = total_yr['teamamt'] + val['teamamt']
            total_yr['teamcount'] = total_yr['teamcount'] + val['teamcount']

    current_label_month = datetime.now().isoformat()[:7]
    if current_label_month in data:
        total_month = data[current_label_month]

    return dict(month=total_month, year=total_yr)


def _performanceByMonth(user_id, months=12, end_month=None, end_year=None):
    monthly_data = SortedDict()

    now = datetime.now()
    if not end_month:
        end_month = now.month
    if not end_year:
        end_year = now.year

    end_time = time.mktime((end_year, end_month + 1, 1, 0, 0, 0, 0, 0, -1))
    start_time = time.mktime((end_year, end_month + 1 - months,
                              1, 0, 0, 0, 0, 0, -1))

    sql = (PerformanceGraph.objects
          .filter_raw('log_activity.created >=',
                      date.fromtimestamp(start_time).isoformat())
          .filter_raw('log_activity.created <',
                      date.fromtimestamp(end_time).isoformat())
          )

    for row in sql.all():
        label = row.approval_created.isoformat()[:7]

        if not label in monthly_data:
            xaxis = row.approval_created.strftime('%b %Y')
            monthly_data[label] = dict(teamcount=0, usercount=0,
                                       teamamt=0, label=xaxis)

        monthly_data[label]['teamamt'] = monthly_data[label]['teamamt'] + 1
        monthly_data_count = monthly_data[label]['teamcount']
        monthly_data[label]['teamcount'] = monthly_data_count + row.total

        if row.user_id == user_id:
            user_count = monthly_data[label]['usercount']
            monthly_data[label]['usercount'] =  user_count + row.total

    # Calculate averages
    for i, vals in monthly_data.items():
        average = round(vals['teamcount'] / float(vals['teamamt']), 1)
        monthly_data[i]['teamavg'] = str(average)  # floats aren't valid json

    return monthly_data;


@editor_required
def motd(request):
    form = None
    if acl.action_allowed(request, 'Admin', 'EditorsMOTD'):
        form = forms.MOTDForm()
    data = context(form=form)
    return jingo.render(request, 'editors/motd.html', data)


@editor_required
@post_required
def save_motd(request):
    if not acl.action_allowed(request, 'Admin', 'EditorsMOTD'):
        return http.HttpResponseForbidden()
    form = forms.MOTDForm(request.POST)
    if form.is_valid():
        set_config('editors_review_motd', form.cleaned_data['motd'])
        return redirect(reverse('editors.motd'))
    data = context(form=form)
    return jingo.render(request, 'editors/motd.html', data)


def _queue(request, TableObj, tab):
    qs = TableObj.Meta.model.objects.all()
    if request.GET:
        search_form = forms.QueueSearchForm(request.GET)
        if search_form.is_valid():
            qs = search_form.filter_qs(qs)
    else:
        search_form = forms.QueueSearchForm()
    review_num = request.GET.get('num', None)
    if review_num:
        try:
            review_num = int(review_num)
        except ValueError:
            pass
        else:
            try:
                # Force a limit query for efficiency:
                start = review_num - 1
                row = qs[start : start + 1][0]
                return redirect('%s?num=%s' % (
                                reverse('editors.review',
                                        args=[row.latest_version_id]),
                                review_num))
            except IndexError:
                pass
    order_by = request.GET.get('sort', '-waiting_time_min')
    legacy_sorts = {
        'name': 'addon_name',
        'age': 'waiting_time_min',
        'type': 'addon_type_id',
    }
    order_by = legacy_sorts.get(order_by, order_by)
    table = TableObj(qs, order_by=order_by)
    default = 100
    per_page = request.GET.get('per_page', default)
    try:
        per_page = int(per_page)
    except ValueError:
        per_page = default
    if per_page <= 0 or per_page > 200:
        per_page = default
    page = paginate(request, table.rows, per_page=per_page)
    table.set_page(page)
    return jingo.render(request, 'editors/queue.html',
                        context(table=table, page=page, tab=tab,
                                search_form=search_form))


def _queue_counts(type=None, **kw):
    def construct_query(query_type, days_min=None, days_max=None):
        def apply_query(query, *args):
            query = query.having(*args)
            return query

        query = query_type.objects

        if days_min:
            query = apply_query(query, 'waiting_time_days >=', days_min)
        if days_max:
            query = apply_query(query, 'waiting_time_days <=', days_max)

        return query.count

    counts = {'pending': construct_query(ViewPendingQueue, **kw),
              'nominated': construct_query(ViewFullReviewQueue, **kw),
              'prelim': construct_query(ViewPreliminaryQueue, **kw),
              'moderated': Review.objects.filter(reviewflag__isnull=False,
                                                 editorreview=1).count}
    rv = {}
    if isinstance(type, basestring):
        return counts[type]()
    for k, v in counts.items():
        if not isinstance(type, list) or k in type:
            rv[k] = v()
    return rv


@editor_required
def queue(request):
    return redirect(reverse('editors.queue_pending'))


@editor_required
def queue_nominated(request):
    return _queue(request, ViewFullReviewQueueTable, 'nominated')


@editor_required
def queue_pending(request):
    return _queue(request, ViewPendingQueueTable, 'pending')


@editor_required
def queue_prelim(request):
    return _queue(request, ViewPreliminaryQueueTable, 'prelim')


@editor_required
def queue_moderated(request):
    rf = (Review.objects.filter(editorreview=1, reviewflag__isnull=False,
                                addon__isnull=False)
                        .order_by('reviewflag__created'))

    page = paginate(request, rf, per_page=20)

    flags = dict(ReviewFlag.FLAGS)

    reviews_formset = ReviewFlagFormSet(request.POST or None,
                                        queryset=page.object_list)

    if reviews_formset.is_valid():
        reviews_formset.save()
        return redirect(reverse('editors.queue_moderated'))

    return jingo.render(request, 'editors/queue.html',
                        context(reviews_formset=reviews_formset,
                                tab='moderated', page=page, flags=flags,
                                search_form=None))


@editor_required
@post_required
@json_view
def application_versions_json(request):
    app_id = request.POST['application_id']
    f = forms.QueueSearchForm()
    return {'choices': f.version_choices_for_app_id(app_id)}


@editor_required
def review(request, version_id):
    version = get_object_or_404(Version, pk=version_id)
    addon = version.addon
    current = addon.current_version

    if (not settings.DEBUG and
        addon.authors.filter(user=request.user).exists()):
        amo.messages.warning(request, _('Self-reviews are not allowed.'))
        return redirect(reverse('editors.queue'))

    form = forms.get_review_form(request.POST or None, request=request,
                                 addon=addon, version=version)

    queue_type = (form.helper.review_type if form.helper.review_type
                  != 'preliminary' else 'prelim')
    redirect_url = reverse('editors.queue_%s' % queue_type)

    num = request.GET.get('num')
    paging = {}
    if num:
        try:
            num = int(num)
        except (ValueError, TypeError):
            raise http.Http404
        total = _queue_counts(queue_type)
        paging = {'current': num, 'total': total,
                  'prev': num > 1, 'next': num < total,
                  'prev_url': '%s?num=%s' % (redirect_url, num - 1),
                  'next_url': '%s?num=%s' % (redirect_url, num + 1)}

    if request.method == 'POST' and form.is_valid():
        form.helper.process()
        if form.cleaned_data.get('notify'):
            EditorSubscription.objects.get_or_create(user=request.amo_user,
                                                     addon=addon)
        amo.messages.success(request, _('Review successfully processed.'))
        return redirect(redirect_url)

    canned = CannedResponse.objects.all()
    is_admin = acl.action_allowed(request, 'Admin', 'EditAnyAddon')
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

    ctx = context(version=version, addon=addon,
                  flags=Review.objects.filter(addon=addon, flag=True),
                  form=form, paging=paging, canned=canned, is_admin=is_admin,
                  status_types=amo.STATUS_CHOICES, show_diff=show_diff,
                  allow_unchecking_files=allow_unchecking_files,
                  actions=actions, actions_minimal=actions_minimal,
                  history=ActivityLog.objects.for_addons(addon)
                          .order_by('created')
                          .filter(action__in=amo.LOG_REVIEW_QUEUE))

    return jingo.render(request, 'editors/review.html', ctx)


@never_cache
@json_view
@editor_required
def review_viewing(request):
    if 'addon_id' not in request.POST:
        return {}

    addon_id = request.POST['addon_id']
    user_id = request.amo_user.id
    current_name = ''
    is_user = 0
    key = '%s:review_viewing:%s' % (settings.CACHE_PREFIX, addon_id)
    interval = amo.EDITOR_VIEWING_INTERVAL

    # Check who is viewing.
    currently_viewing = cache.get(key)

    # If nobody is viewing or current user is, set current user as viewing
    if not currently_viewing or currently_viewing == user_id:
        # We want to save it for twice as long as the ping interval,
        # just to account for latency and the like.
        cache.set(key, user_id, interval * 2)
        currently_viewing = user_id
        current_name = request.amo_user.name
        is_user = 1
    else:
        current_name = UserProfile.objects.get(pk=currently_viewing).name

    return {'current': currently_viewing, 'current_name': current_name,
            'is_user': is_user, 'interval_seconds': interval}


@editor_required
def reviewlog(request):
    data = request.GET.copy()

    if not data.get('start') and not data.get('end'):
        today = date.today()
        data['start'] = date(today.year, today.month, 1)

    form = forms.ReviewLogForm(data)

    approvals = ActivityLog.objects.review_queue()

    if form.is_valid():
        data = form.cleaned_data
        if data['start']:
            approvals = approvals.filter(created__gte=data['start'])
        if data['end']:
            approvals = approvals.filter(created__lt=data['end'])

    pager = amo.utils.paginate(request, approvals, 50)
    ad = {
            amo.LOG.APPROVE_VERSION.id: _('was approved'),
            amo.LOG.PRELIMINARY_VERSION.id: _('given preliminary review'),
            amo.LOG.REJECT_VERSION.id: _('rejected'),
            amo.LOG.ESCALATE_VERSION.id: _('escalated',
                    'editors_review_history_nominated_adminreview'),
            amo.LOG.REQUEST_INFORMATION.id: _('needs more information'),
            amo.LOG.REQUEST_SUPER_REVIEW.id: _('needs super review'),
         }
    data = context(form=form, pager=pager, ACTION_DICT=ad)
    return jingo.render(request, 'editors/reviewlog.html', data)
