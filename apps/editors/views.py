import functools

from django import http
from django.shortcuts import redirect, get_object_or_404
import jingo

import amo
from access import acl
import amo
from amo.decorators import login_required
from devhub.models import ActivityLog
from editors import forms
from editors.models import (ViewPendingQueue, ViewFullReviewQueue,
                            ViewPreliminaryQueue)
from editors.helpers import (ViewPendingQueueTable, ViewFullReviewQueueTable,
                             ViewPreliminaryQueueTable)
from amo.utils import paginate
from amo.urlresolvers import reverse
from files.models import Approval
from zadmin.models import get_config


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

    data = dict(form=form, pager=pager)
    return jingo.render(request, 'editors/eventlog.html', data)


@editor_required
def eventlog_detail(request, id):
    log = get_object_or_404(ActivityLog.objects.editor_events(), pk=id)
    data = dict(log=log)
    return jingo.render(request, 'editors/eventlog_detail.html', data)


@editor_required
def home(request):
    data = dict(reviews_total=Approval.total_reviews(),
                reviews_monthly=Approval.monthly_reviews(),
                motd=get_config('editors_review_motd'),
                eventlog=ActivityLog.objects.editor_events()[:6],
                )

    return jingo.render(request, 'editors/home.html', data)


def _queue(request, TableObj, tab):
    qs = TableObj.Meta.model.objects.all()
    review_num = request.GET.get('num', None)
    if review_num:
        try:
            review_num = int(review_num)
        except ValueError:
            pass
        else:
            try:
                row = qs[review_num - 1]
                return redirect('%s?num=%s' % (
                                reverse('editors.review',
                                        args=[row.latest_version_id]),
                                review_num))
            except IndexError:
                pass
    order_by = request.GET.get('sort', '-waiting_time_days')
    table = TableObj(qs, order_by=order_by)
    queue_counts = {
        'pending': ViewPendingQueue.objects.all().count(),
        'nominated': ViewFullReviewQueue.objects.all().count(),
        'prelim': ViewPreliminaryQueue.objects.all().count(),
        # TODO(Kumar) this is just a placeholder
        'moderated': ViewPendingQueue.objects.all().count()
    }
    page = paginate(request, table.rows, per_page=100,
                    count=queue_counts[tab])
    table.set_page(page)
    return jingo.render(request, 'editors/queue.html',
                        {'table': table, 'page': page, 'tab': tab,
                         'queue_counts': queue_counts})


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
    raise NotImplementedError


@editor_required
def review(request, version_id):
    return http.HttpResponse('Not implemented yet')
