import time
from types import GeneratorType
from datetime import date, datetime

from django import http
from django.shortcuts import get_object_or_404
from django.utils import simplejson
from django.core.serializers.json import DjangoJSONEncoder
from django.core.exceptions import PermissionDenied
from django.views.decorators.cache import cache_control

import jingo

from access import acl
from addons.models import Addon
from amo.urlresolvers import reverse

import unicode_csv
from .db import DayAvg, Avg
from .models import DownloadCount, UpdateCount, Contribution
from .utils import csv_prep, csv_dynamic_prep


SERIES_GROUPS = ('day', 'week', 'month')
SERIES_FORMATS = ('json', 'csv')
SERIES = ('downloads', 'usage', 'contributions',
          'sources', 'os', 'locales', 'statuses', 'versions', 'apps')


def downloads_series(request, addon_id, group, start, end, format):
    """Generate download counts grouped by ``group`` in ``format``."""
    start_date, end_date, addon = check_series_params_or_404(
                                    addon_id, group, start, end, format)
    check_stats_permission(request, addon)

    # resultkey to fieldname map - stored as a list to maintain order for csv
    fields = [('date', 'start'), ('count', 'count')]
    qs = DownloadCount.stats.filter(addon=addon_id,
                                      date__range=(start_date, end_date))
    gen = qs.period_summary(group, **dict(fields))

    if format == 'csv':
        gen, headings = csv_prep(gen, fields)
        return render_csv(request, addon, gen, headings)
    elif format == 'json':
        return render_json(request, addon, gen)


def usage_series(request, addon_id, group, start, end, format):
    """Generate ADU counts grouped by ``group`` in ``format``."""
    start_date, end_date, addon = check_series_params_or_404(
                                    addon_id, group, start, end, format)
    check_stats_permission(request, addon)

    # resultkey to fieldname map - stored as a list to maintain order for csv
    fields = [('date', 'start'), ('count', DayAvg('count'))]
    qs = UpdateCount.stats.filter(addon=addon_id,
                                    date__range=(start_date, end_date))
    gen = qs.period_summary(group, **dict(fields))

    if format == 'csv':
        gen, headings = csv_prep(gen, fields)
        return render_csv(request, addon, gen, headings)
    elif format == 'json':
        return render_json(request, addon, gen)


def contributions_series(request, addon_id, group, start, end, format):
    """Generate summarized contributions grouped by ``group`` in ``format``."""
    start_date, end_date, addon = check_series_params_or_404(
                                    addon_id, group, start, end, format)
    check_stats_permission(request, addon, for_contributions=True)

    qs = addon_contributions_queryset(addon, start_date, end_date)

    # Note that average is per contribution and not per day
    fields = [('date', 'start'), ('total', 'amount'), ('count', 'row_count'),
              ('average', Avg('amount'))]
    gen = qs.period_summary(group, **dict(fields))

    if format == 'csv':
        gen, headings = csv_prep(gen, fields, precision='0.01')
        return render_csv(request, addon, gen, headings)
    elif format == 'json':
        return render_json(request, addon, gen)


def contributions_detail(request, addon_id, start, end, format):
    """Generate detailed contributions in ``format``."""
    # This view doesn't do grouping, but we can leverage our series parameter
    # checker by passing in a valid group value.
    start_date, end_date, addon = check_series_params_or_404(
                                    addon_id, 'day', start, end, format)
    check_stats_permission(request, addon, for_contributions=True)

    qs = addon_contributions_queryset(addon, start_date, end_date)

    def property_lookup_gen(qs, fields):
        for obj in qs:
            yield dict((k, getattr(obj, f, None)) for k, f in fields)

    fields = [('date', 'date'), ('amount', 'amount'),
              ('requested', 'suggested_amount'),
              ('contributor', 'contributor'),
              ('email', 'email'), ('comment', 'comment')]
    gen = property_lookup_gen(qs, fields)

    if format == 'csv':
        gen, headings = csv_prep(gen, fields, precision='0.01')
        return render_csv(request, addon, gen, headings)
    elif format == 'json':
        return render_json(request, addon, gen)


def sources_series(request, addon_id, group, start, end, format):
    """Generate download source breakdown."""
    start_date, end_date, addon = check_series_params_or_404(
                                    addon_id, group, start, end, format)
    check_stats_permission(request, addon)

    # resultkey to fieldname map - stored as a list to maintain order for csv
    fields = [('date', 'start'), ('count', 'count'), ('sources', 'sources')]
    qs = DownloadCount.stats.filter(addon=addon_id,
                                      date__range=(start_date, end_date))
    gen = qs.period_summary(group, **dict(fields))

    if format == 'csv':
        gen, headings = csv_dynamic_prep(gen, qs, fields, 'count', 'sources')
        return render_csv(request, addon, gen, headings)
    elif format == 'json':
        return render_json(request, addon, gen)


def usage_breakdown_series(request, addon_id, group,
                           start, end, format, field):
    """Generate ADU breakdown of ``field``."""
    start_date, end_date, addon = check_series_params_or_404(
                                    addon_id, group, start, end, format)
    check_stats_permission(request, addon)

    # resultkey to fieldname map - stored as a list to maintain order for csv
    # Use DayAvg so days with 0 rows affect the calculation.
    fields = [('date', 'start'), ('count', DayAvg('count')),
              (field, DayAvg(field))]
    qs = UpdateCount.stats.filter(addon=addon_id,
                                    date__range=(start_date, end_date))
    gen = qs.period_summary(group, **dict(fields))

    if format == 'csv':
        gen, headings = csv_dynamic_prep(gen, qs, fields,
                                         'count', field)
        return render_csv(request, addon, gen, headings)
    elif format == 'json':
        return render_json(request, addon, gen)


def check_series_params_or_404(addon_id, group, start, end, format):
    """Check common series parameters."""
    if (group not in SERIES_GROUPS) or (format not in SERIES_FORMATS):
        raise http.Http404
    (start_date, end_date) = get_daterange_or_404(start, end)
    addon = get_object_or_404(Addon, id=addon_id)
    return (start_date, end_date, addon)


def check_stats_permission(request, addon, for_contributions=False):
    """Check if user is allowed to view stats for ``addon``.

    Raises PermissionDenied if user is not allowed.
    """
    if for_contributions or not addon.public_stats:
        # only authenticated admins and authors
        if (request.user.is_authenticated() and (
                acl.action_allowed(request, 'Admin', 'ViewAnyStats') or
                addon.has_author(request.amo_user))):
            return
    elif addon.public_stats:
        # non-contributions, public: everybody can view
        return
    raise PermissionDenied


def stats_report(request, addon_id, report):
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)
    check_stats_permission(request, addon)
    stats_base_url = reverse('stats.overview', args=[addon.id])
    view = get_report_view(request)
    return jingo.render(request, 'stats/%s.html' % report,
                        {'addon': addon,
                        'report': report,
                        'view': view,
                        'stats_base_url': stats_base_url})


def get_report_view(request):
    """Parse and validate a pair of YYYMMDD date strings."""
    if ('start' in request.GET and
        'end' in request.GET):
        try:
            start = request.GET.get('start')
            end = request.GET.get('end')

            assert len(start) == 8
            assert len(end) == 8

            s_year = int(start[0:4])
            s_month = int(start[4:6])
            s_day = int(start[6:8])
            e_year = int(end[0:4])
            e_month = int(end[4:6])
            e_day = int(end[6:8])

            date(s_year, s_month, s_day)
            date(e_year, e_month, e_day)

            return {'range': 'custom',
                    'start': start,
                    'end': end}
        except (KeyError, AssertionError, ValueError):
            pass

    if 'last' in request.GET:
        daterange = request.GET.get('last')

        return {'range': daterange, 'last': daterange}
    else:
        return {'range': '30', 'last': '30'}


def get_daterange_or_404(start, end):
    """Parse and validate a pair of YYYMMDD date strings."""
    try:
        assert len(start) == 8
        assert len(end) == 8

        s_year = int(start[0:4])
        s_month = int(start[4:6])
        s_day = int(start[6:8])
        e_year = int(end[0:4])
        e_month = int(end[4:6])
        e_day = int(end[6:8])

        start_date = date(s_year, s_month, s_day)
        end_date = date(e_year, e_month, e_day)
    except (AssertionError, ValueError):
        raise http.Http404
    return (start_date, end_date)


def addon_contributions_queryset(addon, start_date, end_date):
    """Return a Contribution queryset common to all contribution views."""
    # Contribution.created is a datetime.
    # Make sure we include all on the last day of the range.
    if not isinstance(end_date, datetime):
        end_date = datetime(end_date.year, end_date.month,
                            end_date.day, 23, 59, 59)

    return Contribution.stats.filter(addon=addon,
                                     transaction_id__isnull=False,
                                     amount__gt=0,
                                     created__range=(start_date, end_date))

# 30 days in seconds:
thirty_days = 60 * 60 * 24 * 30


@cache_control(max_age=thirty_days)
def render_csv(request, addon, stats, fields):
    """Render a stats series in CSV."""
    # Start with a header from the template.
    ts = time.strftime('%c %z')
    response = jingo.render(request, 'stats/csv_header.txt',
                            {'addon': addon, 'fields': fields,
                             'timestamp': ts})

    # For remora compatibility, reverse the output so oldest data
    # is first.
    # XXX: The list() performance penalty here might be big enough to
    # consider changing the sort order at lower levels.
    writer = unicode_csv.UnicodeWriter(response)
    for row in reversed(list(stats)):
        writer.writerow(row)

    response['Content-Type'] = 'text/plain; charset=utf-8'
    return response


@cache_control(max_age=thirty_days)
def render_json(request, addon, stats):
    """Render a stats series in JSON."""
    response = http.HttpResponse(mimetype='text/json')

    # XXX: Subclass DjangoJSONEncoder to handle generators.
    if isinstance(stats, GeneratorType):
        stats = list(stats)

    # Django's encoder supports date and datetime.
    simplejson.dump(stats, response, cls=DjangoJSONEncoder)
    return response
