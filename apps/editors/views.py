import functools

from django import http
from django.shortcuts import redirect
from django.core.paginator import Paginator
import jingo

from access import acl
from amo.decorators import login_required
from editors.models import ViewEditorQueue
from editors.helpers import ViewEditorQueueTable
from amo.utils import paginate
from amo.urlresolvers import reverse
from files.models import Approval


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
def home(request):
    data = {'reviews_total': Approval.total_reviews(),
            'reviews_monthly': Approval.monthly_reviews()}

    return jingo.render(request, 'editors/home.html', data)


@editor_required
def queue(request):
    return redirect(reverse('editors.queue_pending'))


@editor_required
def queue_pending(request):
    qs = ViewEditorQueue.objects.all()
    review_num = request.GET.get('num', None)
    if review_num:
        try:
            review_num = int(review_num)
        except ValueError:
            pass
        else:
            try:
                row = qs[review_num - 1]
                return redirect('%s?num=%s' % (reverse('editors.review',
                                                       args=[row.version_id]),
                                               review_num))
            except IndexError:
                pass
    order_by = request.GET.get('sort', '-days_since_created')
    table = ViewEditorQueueTable(qs, order_by=order_by)
    queue_count = qs.count()
    page = paginate(request, table.rows, per_page=100, count=queue_count)
    table.set_page(page)
    return jingo.render(request, 'editors/queue/pending.html',
                        {'table': table, 'page': page,
                         'queue_count': queue_count})


@editor_required
def review(request, version_id):
    return http.HttpResponse('Not implemented yet')
