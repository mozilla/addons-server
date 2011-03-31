from datetime import date
import functools

from django import http
from django.conf import settings
from django.shortcuts import redirect, get_object_or_404

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
                            EventLog, CannedResponse)
from editors.helpers import (ViewPendingQueueTable, ViewFullReviewQueueTable,
                             ViewPreliminaryQueueTable, LOG_STATUSES)
from files.models import Approval
from reviews.forms import ReviewFlagFormSet
from reviews.models import Review, ReviewFlag
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
    data = context(reviews_total=Approval.total_reviews(),
                   reviews_monthly=Approval.monthly_reviews(),
                   new_editors=EventLog.new_editors(),
                   eventlog=ActivityLog.objects.editor_events()[:6])

    return jingo.render(request, 'editors/home.html', data)


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
                row = qs[review_num - 1:1][0]
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


def _queue_counts(type=None):
    counts = {'pending': ViewPendingQueue.objects.count,
              'nominated': ViewFullReviewQueue.objects.count,
              'prelim': ViewPreliminaryQueue.objects.count,
              'moderated': Review.objects.filter(reviewflag__isnull=False,
                                                 editorreview=1).count}
    if type:
        return counts[type]()
    for k, v in counts.items():
        counts[k] = v()
    return counts


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

    has_public_files = (current.files.filter(status=amo.STATUS_PUBLIC)
                                     .exists()) if current else False
    # The actions we should show a minimal form from.
    actions_minimal = [k for (k, a) in actions if not a.get('minimal')]

    # We only allow the user to check/uncheck files for "pending"
    allow_unchecking_files = form.helper.review_type == "pending"

    ctx = context(version=version, addon=addon,
                  flags=Review.objects.filter(addon=addon, flag=True),
                  form=form, paging=paging, canned=canned, is_admin=is_admin,
                  status_types=amo.STATUS_CHOICES,
                  has_public_files=has_public_files,
                  allow_unchecking_files=allow_unchecking_files,
                  actions=actions, actions_minimal=actions_minimal,
                  history=ActivityLog.objects.for_addons(addon)
                          .order_by('created')
                          .filter(action__in=LOG_STATUSES))

    return jingo.render(request, 'editors/review.html', ctx)


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
         }
    data = context(form=form, pager=pager, ACTION_DICT=ad)
    return jingo.render(request, 'editors/reviewlog.html', data)
