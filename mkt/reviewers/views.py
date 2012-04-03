from django import http
from django.conf import settings
from django.db.models import Count
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
from editors.models import CannedResponse, EditorSubscription
from editors.views import reviewer_required
from reviews.models import Review
from zadmin.models import get_config

from mkt.webapps.models import Webapp
from . import forms, utils


@reviewer_required
def home(request):
    # TODO: Implement landing page for apps (bug 741634).
    return redirect('reviewers.queue_apps')


def queue_counts(type_=None, **kw):
    counts = {'apps': Webapp.objects.pending().count}
    if type_:
        # Evaluate count for only this type.
        return counts.get(type_)()
    else:
        # Evaluate all counts.
        return dict((k, v()) for k, v in counts.iteritems())


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
    default = 10  # TODO: Change to 100.
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
    ctx = dict(motd=get_config('editors_review_motd'),
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
    redirect_url = reverse('reviewers.queue_%s' % queue_type)

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

    canned = CannedResponse.objects.all()
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
    return _queue(request, utils.WebappQueueTable, 'apps', qs=qs)
