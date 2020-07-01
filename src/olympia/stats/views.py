import csv
import json
import time
import itertools

from datetime import timedelta, datetime

from dateutil.parser import parse
from django import http
from django.core.exceptions import PermissionDenied
from django.core.files.storage import get_storage_class
from django.db.transaction import non_atomic_requests
from django.utils.cache import add_never_cache_headers, patch_cache_control
from django.utils.encoding import force_text

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.amo.decorators import allow_cross_site_request
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import AMOJSONEncoder, render
from olympia.core.languages import ALL_LANGUAGES
from olympia.stats.decorators import addon_view_stats
from olympia.stats.forms import DateForm

from .models import DownloadCount
from .utils import get_updates_series


logger = olympia.core.logger.getLogger('z.apps.stats.views')


SERIES_GROUPS = ('day', 'week', 'month')
SERIES_GROUPS_DATE = ('date', 'week', 'month')  # Backwards compat.
SERIES_FORMATS = ('json', 'csv')
SERIES = ('downloads', 'usage', 'overview', 'sources', 'os', 'locales',
          'versions', 'apps', 'countries',)


storage = get_storage_class()()


def get_series(model, extra_field=None, source=None, **filters):
    """
    Get a generator of dicts for the stats model given by the filters.

    Returns {'date': , 'count': } by default. Add an extra field (such as
    application faceting) by passing `extra_field=apps`. `apps` should be in
    the query result.
    """
    extra = () if extra_field is None else (extra_field,)
    # Put a slice on it so we get more than 10 (the default), but limit to 365.
    qs = (model.search().order_by('-date').filter(**filters)
          .values_dict('date', 'count', *extra))
    if source:
        qs = qs.source(source)
    for val in qs[:365]:
        # Convert the datetimes to a date.
        date_ = parse(val['date']).date()
        rv = {'count': val['count'], 'date': date_, 'end': date_}
        if source:
            rv['data'] = extract(val[source])
        elif extra_field:
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
    # Sort the fields before returning them - we don't care much about column
    # ordering, but it helps make the tests stable.
    return rv, sorted(fields, key=lambda field: '' if not field else field)


def extract(dicts):
    """Turn a list of dicts like we store in ES into one big dict.

    Also works if the list of dicts is nested inside another dict.

    >>> extract([{'k': 'a', 'v': 1}, {'k': 'b', 'v': 2}])
    {'a': 1, 'b': 2}

    >>> extract({'k': 'a', 'v': 1})
    {'a': 1}

    >>> extract([{'mykey': [{'k': 'a', 'v': 1}, {'k': 'b', 'v': 2}]}])
    {'mykey': {'a': 1, 'b': 2}}

    >>> extract({'mykey': [{'k': 'a', 'v': 1}, {'k': 'b', 'v': 2}]})
    {'mykey': {'a': 1, 'b': 2}}

    >>> extract([{'mykey': {'k': 'a', 'v': 1}}])
    {'mykey': {'a': 1}}

    >>> extract({'mykey': {'k': 'a', 'v': 1}})
    {'mykey': {'a': 1}}
    """

    def _extract_value(data):
        # We are already dealing with a dict. If it has 'k' and 'v' keys,
        # then we can just return that.
        if 'k' in data and 'v' in data:
            return ((data['k'], data['v']),)
        # Otherwise re-extract the value.
        return ((k, extract(v)) for k, v in data.items())

    if hasattr(dicts, 'items'):
        # If it's already a dict, we just need to call extract_value which will
        # iterate if necessary.
        return dict(_extract_value(dicts))
    extracted = {}
    for d in dicts:
        extracted.update(extract(d))
    return extracted


@addon_view_stats
@non_atomic_requests
def overview_series(request, addon, group, start, end, format):
    """Combines downloads_series and updates_series into one payload."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    dls = get_series(DownloadCount, addon=addon.id, date__range=date_range)

    updates = get_updates_series(addon=addon,
                                 start_date=date_range[0],
                                 end_date=date_range[1])

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
        if isinstance(d, str):
            d = datetime.strptime(d, '%Y-%m-%d').date()
        start_date = max(start_date, d) if start_date else d
    downloads, updates = iter(downloads), iter(updates)

    def iterator(series):
        try:
            item = next(series)
            next_date = start_date
            while True:
                date = item['date']
                if isinstance(date, str):
                    date = datetime.strptime(date, '%Y-%m-%d').date()
                if date == next_date:
                    yield item['count']
                    item = next(series)
                else:
                    yield 0
                next_date = next_date - timedelta(days=1)
        except StopIteration:
            pass

    series = itertools.zip_longest(iterator(downloads), iterator(updates))
    for idx, (dl_count, up_count) in enumerate(series):
        yield {'date': start_date - timedelta(days=idx),
               'data': {'downloads': dl_count, 'updates': up_count}}


@addon_view_stats
@non_atomic_requests
def downloads_series(request, addon, group, start, end, format):
    """Generate download counts grouped by ``group`` in ``format``."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series(DownloadCount, addon=addon.id, date__range=date_range)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


@addon_view_stats
@non_atomic_requests
def sources_series(request, addon, group, start, end, format):
    """Generate download source breakdown."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series(DownloadCount, source='sources',
                        addon=addon.id, date__range=date_range)

    if format == 'csv':
        series, fields = csv_fields(series)
        return render_csv(request, addon, series,
                          ['date', 'count'] + list(fields))
    elif format == 'json':
        return render_json(request, addon, series)


@addon_view_stats
@non_atomic_requests
def usage_series(request, addon, group, start, end, format):
    """Generate ADU counts grouped by ``group`` in ``format``."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_updates_series(addon=addon,
                                start_date=date_range[0],
                                end_date=date_range[1])

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


@addon_view_stats
@non_atomic_requests
def usage_breakdown_series(request, addon, group, start, end, format, field):
    """Generate ADU breakdown of ``field``."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    fields = {
        'applications': 'apps',
        'countries': 'countries',
        'locales': 'locales',
        'oses': 'os',
        'statuses': 'status',
        'versions': 'versions',
    }
    source = fields[field]

    series = get_updates_series(addon=addon,
                                start_date=date_range[0],
                                end_date=date_range[1], source=source)

    if field == 'locales':
        series = process_locales(series)

    if format == 'csv':
        if field == 'applications':
            series = flatten_applications(series)
        series, fields = csv_fields(series)
        return render_csv(request, addon, series,
                          ['date', 'count'] + list(fields))
    elif format == 'json':
        return render_json(request, addon, series)


def flatten_applications(series):
    """Convert app guids to pretty names, flatten count structure."""
    for row in series:
        if 'data' in row:
            new = {}
            for app, versions in row['data'].items():
                app = amo.APP_GUIDS.get(app)
                if not app:
                    continue
                # str() to decode the gettext proxy.
                appname = str(app.pretty)
                for ver, count in versions.items():
                    key = ' '.join([appname, ver])
                    new[key] = count
            row['data'] = new
        yield row


def process_locales(series):
    """Convert locale codes to pretty names, skip any unknown locales."""
    languages = {
        key.lower(): value['native']
        for key, value in ALL_LANGUAGES.items()}

    for row in series:
        if 'data' in row:
            new = {}
            for key, count in row['data'].items():
                if key and key.lower() in languages:
                    k = '%s (%s)' % (languages[key.lower()], key)
                    new[k] = count
            row['data'] = new
        yield row


def check_series_params_or_404(group, start, end, format):
    """Check common series parameters."""
    if (group not in SERIES_GROUPS) or (format not in SERIES_FORMATS):
        raise http.Http404
    return get_daterange_or_404(start, end)


def check_stats_permission(request, addon):
    """
    Check if user is allowed to view stats for ``addon``.

    Raises PermissionDenied if user is not allowed.

    Raises Http404 if ``addon`` does not have stats pages.
    """
    user = request.user

    if addon.type not in amo.ADDON_TYPES_WITH_STATS:
        raise http.Http404

    can_view = user.is_authenticated and (
        addon.has_author(user) or
        acl.action_allowed(request, amo.permissions.STATS_VIEW)
    )
    if not can_view:
        raise PermissionDenied


@addon_view_stats
@non_atomic_requests
def stats_report(request, addon, report):
    check_stats_permission(request, addon)
    stats_base_url = reverse('stats.overview', args=[addon.slug])
    view = get_report_view(request)

    return render(
        request,
        'stats/reports/%s.html' % report,
        {
            'addon': addon,
            'report': report,
            'stats_base_url': stats_base_url,
            'view': view,
        }
    )


def get_report_view(request):
    """Parse and validate a pair of YYYMMDD date strings."""
    dates = DateForm(data=request.GET)
    if not dates.is_valid():
        logger.info('Dates parsed were not valid.')
        return {}

    if dates.cleaned_data.get('start') and dates.cleaned_data.get('end'):
        return {
            'range': 'custom',
            'start': dates.cleaned_data['start'].strftime('%Y%m%d'),
            'end': dates.cleaned_data['end'].strftime('%Y%m%d'),
        }

    elif dates.cleaned_data.get('last'):
        return {
            'range': dates.cleaned_data['last'],
            'last': str(dates.cleaned_data['last']) + ' days'
        }

    logger.info('Missing "start and end" or "last"')
    return {}


def get_daterange_or_404(start, end):
    """Parse and validate a pair of YYYYMMDD date strings."""
    dates = DateForm(data={'start': start, 'end': end})
    if not dates.is_valid():
        logger.info('Dates parsed were not valid.')
        raise http.Http404

    return (
        dates.cleaned_data['start'],
        dates.cleaned_data['end']
    )


def fudge_headers(response, stats):
    """Alter cache headers. Don't cache content where data could be missing."""
    if not stats:
        add_never_cache_headers(response)
    else:
        seven_days = 60 * 60 * 24 * 7
        patch_cache_control(response, max_age=seven_days)


@allow_cross_site_request
@non_atomic_requests
def render_csv(request, addon, stats, fields,
               title=None, show_disclaimer=None):
    """Render a stats series in CSV."""
    # Start with a header from the template.
    ts = time.strftime('%c %z')
    context = {'addon': addon, 'timestamp': ts, 'title': title,
               'show_disclaimer': show_disclaimer}
    response = render(request, 'stats/csv_header.txt', context)
    writer = csv.DictWriter(
        response, fields, restval=0, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(stats)

    fudge_headers(response, stats)
    response['Content-Type'] = 'text/csv; charset=utf-8'
    return response


@allow_cross_site_request
@non_atomic_requests
def render_json(request, addon, stats):
    """Render a stats series in JSON."""
    response = http.HttpResponse(content_type='application/json')

    # Django's encoder supports date and datetime.
    json.dump(stats, response, cls=AMOJSONEncoder)
    fudge_headers(response, force_text(response.content) != json.dumps([]))
    return response
