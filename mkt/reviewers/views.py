import datetime

from django import http
from django.conf import settings
from django.db.models import Count, Q
from django.shortcuts import redirect

import jingo
from tower import ugettext as _

from access import acl
import amo
from amo import messages
from addons.decorators import addon_view
from addons.models import Version
from amo.decorators import permission_required
from amo.urlresolvers import reverse
from amo.utils import paginate
from editors.forms import MOTDForm
from editors.models import EditorSubscription
from editors.views import reviewer_required
from reviews.models import Review
from zadmin.models import get_config, set_config

from mkt.developers.models import ActivityLog
from mkt.webapps.models import Webapp
from . import forms, utils
from .models import AppCannedResponse


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


def queue_counts(type=None, **kw):
    counts = {
        'pending': Webapp.objects.pending().count()
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
    qs = Webapp.objects.pending()
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


def _queue(request, TableObj, tab, qs=None):
    if qs is None:
        qs = TableObj.Meta.model.objects.all()
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
                row = qs[start: start + 1][0]
                return redirect('%s?num=%s' % (
                                TableObj.review_url(row),
                                review_num))
            except IndexError:
                pass
    order_by = request.GET.get('sort', TableObj.default_order_by())
    order_by = TableObj.translate_sort_cols(order_by)
    table = TableObj(data=qs, order_by=order_by)
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
    return jingo.render(request, 'reviewers/queue.html',
                        context(table=table, page=page, tab=tab))


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

    queue_type = (form.helper.review_type if form.helper.review_type
                  != 'preliminary' else 'prelim')
    redirect_url = reverse('reviewers.apps.queue_%s' % queue_type)

    num = request.GET.get('num')
    paging = {}
    if num:
        try:
            num = int(num)
        except (ValueError, TypeError):
            raise http.Http404
        total = queue_counts(queue_type)
        paging = {'current': num, 'total': total,
                  'prev': num > 1, 'next': num < total,
                  'prev_url': '%s?num=%s' % (redirect_url, num - 1),
                  'next_url': '%s?num=%s' % (redirect_url, num + 1)}

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

    ctx = context(version=version, product=addon,
                  pager=pager, num_pages=num_pages, count=count,
                  flags=Review.objects.filter(addon=addon, flag=True),
                  form=form, paging=paging, canned=canned, is_admin=is_admin,
                  status_types=amo.STATUS_CHOICES, show_diff=show_diff,
                  allow_unchecking_files=allow_unchecking_files,
                  actions=actions, actions_minimal=actions_minimal)

    return jingo.render(request, 'reviewers/review.html', ctx)


@permission_required('Apps', 'Review')
@addon_view
def app_review(request, addon):
    return _review(request, addon)


@permission_required('Apps', 'Review')
def queue_apps(request):
    qs = Webapp.objects.pending().annotate(Count('abuse_reports'))
    return _queue(request, utils.WebappQueueTable, 'pending', qs=qs)


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
