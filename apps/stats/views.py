import csv
import cStringIO
import itertools
import time
from types import GeneratorType
from datetime import date, timedelta

from django import http
from django.db.models import Avg, Count, Sum
from django.utils import simplejson
from django.utils.cache import add_never_cache_headers, patch_cache_control
from django.core.serializers.json import DjangoJSONEncoder
from django.core.exceptions import PermissionDenied

import jingo
from product_details import product_details

from access import acl
from addons.decorators import addon_view, addon_view_factory
from addons.models import Addon
from amo.urlresolvers import reverse

from .decorators import allow_cross_site_request
from .models import DownloadCount, UpdateCount, Contribution


SERIES_GROUPS = ('day', 'week', 'month')
SERIES_FORMATS = ('json', 'csv')
SERIES = ('downloads', 'usage', 'contributions', 'overview',
          'sources', 'os', 'locales', 'statuses', 'versions', 'apps')


def get_series(model, extra_field=None, **filters):
    """
    Get a generator of dicts for the stats model given by the filters.

    Returns {'date': , 'count': } by default. Add an extra field (such as
    application faceting) by passing `extra_field=apps`. `apps` should be in
    the query result.
    """
    extra = () if extra_field is None else (extra_field,)
    # Put a slice on it so we get more than 10 (the default), but limit to 365.
    qs = (model.search().order_by('-date').filter(**filters)
          .values_dict('date', 'count', *extra))[:365]
    for val in qs:
        # Convert the datetimes to a date.
        date_ = date(*val['date'].timetuple()[:3])
        rv = dict(count=val['count'], date=date_, end=date_)
        if extra_field:
            rv['data'] = extract(val[extra_field])
        yield rv


def csv_fields(series):
    """
    Figure out all the keys in the `data` dict for csv columns.

    Returns (series, fields). The series only contains the `data` dicts, plus
    `count` and `date` from the top level.
    """
    rv = []
    fields = set()
    for row in series:
        fields.update(row['data'])
        rv.append(row['data'])
        row['data'].update(count=row['count'], date=row['date'])
    return rv, fields


def extract(dicts):
    """Turn a list of dicts like we store in ES into one big dict.

    Also works if the list of dicts is nested inside another dict.

    >>> extract([{'k': 'a', 'v': 1}, {'k': 'b', 'v': 2}])
    {'a': 1, 'b': 2}
    """
    if hasattr(dicts, 'items'):
        return dict((k, extract(v)) for k, v in dicts.items())
    return dict((d['k'], d['v']) for d in dicts)


@addon_view
def overview_series(request, addon, group, start, end, format):
    """Combines downloads_series and updates_series into one payload."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    dls = get_series(DownloadCount, addon=addon.id, date__range=date_range)
    updates = get_series(UpdateCount, addon=addon.id, date__range=date_range)

    series = zip_overview(dls, updates)

    return render_json(request, addon, series)


def zip_overview(downloads, updates):
    # Jump through some hoops to make sure we're matching dates across download
    # and update series and inserting zeroes for any missing days.
    downloads, updates = list(downloads), list(updates)
    if not (downloads or updates):
        return
    start_date = None
    if downloads:
        start_date = downloads[0]['date']
    if updates:
        d = updates[0]['date']
        start_date = max(start_date, d) if start_date else d
    downloads, updates = iter(downloads), iter(updates)

    def iterator(series):
        item = next(series)
        next_date = start_date
        while 1:
            if item['date'] == next_date:
                yield item['count']
                item = next(series)
            else:
                yield 0
            next_date = next_date - timedelta(days=1)

    series = itertools.izip_longest(iterator(downloads), iterator(updates))
    for idx, (dl_count, up_count) in enumerate(series):
        yield {'date': start_date - timedelta(days=idx),
               'data': {'downloads': dl_count, 'updates': up_count}}


@addon_view
def downloads_series(request, addon, group, start, end, format):
    """Generate download counts grouped by ``group`` in ``format``."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series(DownloadCount, addon=addon.id, date__range=date_range)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


@addon_view
def sources_series(request, addon, group, start, end, format):
    """Generate download source breakdown."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series(DownloadCount, extra_field='_source.sources',
                        addon=addon.id, date__range=date_range)

    if format == 'csv':
        series, fields = csv_fields(series)
        return render_csv(request, addon, series,
                          ['date', 'count'] + list(fields))
    elif format == 'json':
        return render_json(request, addon, series)


@addon_view
def usage_series(request, addon, group, start, end, format):
    """Generate ADU counts grouped by ``group`` in ``format``."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series(UpdateCount, addon=addon.id, date__range=date_range)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


@addon_view
def usage_breakdown_series(request, addon, group,
                           start, end, format, field):
    """Generate ADU breakdown of ``field``."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    fields = {
        'applications': '_source.apps',
        'locales': '_source.locales',
        'oses': '_source.os',
        'versions': '_source.versions',
        'statuses': '_source.status',
    }
    series = get_series(UpdateCount, extra_field=fields[field],
                        addon=addon.id, date__range=date_range)
    if field == 'locales':
        series = process_locales(series)

    if format == 'csv':
        series, fields = csv_fields(series)
        return render_csv(request, addon, series,
                          ['date', 'count'] + list(fields))
    elif format == 'json':
        return render_json(request, addon, series)


def process_locales(series):
    """Convert locale codes to pretty names, skip any unknown locales."""
    languages = dict((k.lower(), v['native'])
                     for k, v in product_details.languages.items())
    for row in series:
        if 'data' in row:
            new = {}
            for key, count in row['data'].items():
                if key in languages:
                    k = u'%s (%s)' % (languages[key], key)
                    new[k] = count
            row['data'] = new
        yield row


def check_series_params_or_404(group, start, end, format):
    """Check common series parameters."""
    if (group not in SERIES_GROUPS) or (format not in SERIES_FORMATS):
        raise http.Http404
    return get_daterange_or_404(start, end)


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


@addon_view_factory(Addon.objects.valid)
def stats_report(request, addon, report):
    check_stats_permission(request, addon,
                           for_contributions=(report == 'contributions'))
    stats_base_url = reverse('stats.overview', args=[addon.slug])
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


@addon_view
def contributions_series(request, addon, group, start, end, format):
    """Generate summarized contributions grouped by ``group`` in ``format``."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon, for_contributions=True)

    # Beware: this needs to scan all the matching rows to do aggregates.
    qs = (Contribution.objects.extra(select={'date_created': 'date(created)'})
          .filter(addon=addon, amount__gt=0, transaction_id__isnull=False,
                  created__range=date_range)
          .values('date_created')
          .annotate(count=Count('amount'), average=Avg('amount'),
                    total=Sum('amount')))

    # Add `date` and `end` keys for legacy compat.
    series = sorted(qs, key=lambda x: x['date_created'], reverse=True)
    for row in series:
        row['end'] = row['date'] = row.pop('date_created')

    if format == 'csv':
        return render_csv(request, addon, series,
                          ['date', 'count', 'total', 'average'])
    elif format == 'json':
        return render_json(request, addon, series)


def fudge_headers(response, stats):
    """Alter cache headers. Don't cache content where data could be missing."""
    if not stats:
        add_never_cache_headers(response)
    else:
        seven_days = 60 * 60 * 24 * 7
        patch_cache_control(response, max_age=seven_days)


class UnicodeCSVDictWriter(csv.DictWriter):
    """A DictWriter that writes a unicode stream."""

    def __init__(self, stream, fields, **kw):
        # We have the csv module write into our buffer as bytes and then we
        # dump the buffer to the real stream as unicode.
        self.buffer = cStringIO.StringIO()
        csv.DictWriter.__init__(self, self.buffer, fields, **kw)
        self.stream = stream

    def writeheader(self):
        self.writerow(dict(zip(self.fieldnames, self.fieldnames)))

    def try_encode(self, obj):
        return obj.encode('utf-8') if isinstance(obj, unicode) else obj

    def writerow(self, rowdict):
        row = self._dict_to_list(rowdict)
        # Write to the buffer as ascii.
        self.writer.writerow(map(self.try_encode, row))
        # Dump the buffer to the real stream as utf-8.
        self.stream.write(self.buffer.getvalue().decode('utf-8'))
        # Clear the buffer.
        self.buffer.truncate(0)

    def writerows(self, rowdicts):
        for rowdict in rowdicts:
            self.writerow(rowdict)


@allow_cross_site_request
def render_csv(request, addon, stats, fields):
    """Render a stats series in CSV."""
    # Start with a header from the template.
    ts = time.strftime('%c %z')
    response = jingo.render(request, 'stats/csv_header.txt',
                            {'addon': addon, 'timestamp': ts})

    writer = UnicodeCSVDictWriter(response, fields, restval=0,
                                  extrasaction='ignore')
    writer.writeheader()
    writer.writerows(stats)

    fudge_headers(response, list)
    response['Content-Type'] = 'text/csv; charset=utf-8'
    return response


@allow_cross_site_request
def render_json(request, addon, stats):
    """Render a stats series in JSON."""
    response = http.HttpResponse(mimetype='text/json')

    # XXX: Subclass DjangoJSONEncoder to handle generators.
    if isinstance(stats, GeneratorType):
        stats = list(stats)

    # Django's encoder supports date and datetime.
    fudge_headers(response, stats)
    simplejson.dump(stats, response, cls=DjangoJSONEncoder)
    return response
