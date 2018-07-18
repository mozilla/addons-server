import cStringIO
import csv
import itertools
import json
import time

from collections import OrderedDict
from datetime import date, timedelta

from django import http
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.storage import get_storage_class
from django.db import connection
from django.db.models import Q
from django.db.transaction import non_atomic_requests
from django.shortcuts import get_object_or_404
from django.utils.cache import add_never_cache_headers, patch_cache_control

from dateutil.parser import parse
from product_details import product_details

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.addons.decorators import addon_view_factory
from olympia.addons.models import Addon
from olympia.lib.cache import memoize
from olympia.amo.decorators import (
    allow_cross_site_request,
    json_view,
    login_required,
)
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import AMOJSONEncoder, render
from olympia.bandwagon.models import Collection
from olympia.bandwagon.views import get_collection
from olympia.stats.forms import DateForm
from olympia.zadmin.models import SiteEvent

from .models import CollectionCount, DownloadCount, ThemeUserCount, UpdateCount


logger = olympia.core.logger.getLogger('z.apps.stats.views')


SERIES_GROUPS = ('day', 'week', 'month')
SERIES_GROUPS_DATE = ('date', 'week', 'month')  # Backwards compat.
SERIES_FORMATS = ('json', 'csv')
SERIES = (
    'downloads',
    'usage',
    'overview',
    'sources',
    'os',
    'locales',
    'statuses',
    'versions',
    'apps',
)
COLLECTION_SERIES = ('downloads', 'subscribers', 'ratings')
GLOBAL_SERIES = (
    'addons_in_use',
    'addons_updated',
    'addons_downloaded',
    'collections_created',
    'reviews_created',
    'addons_created',
    'users_created',
    'my_apps',
)


addon_view = addon_view_factory(qs=Addon.objects.valid)
storage = get_storage_class()()


@non_atomic_requests
def dashboard(request):
    stats_base_url = reverse('stats.dashboard')
    view = get_report_view(request)
    return render(
        request,
        'stats/dashboard.html',
        {'report': 'site', 'view': view, 'stats_base_url': stats_base_url},
    )


def get_series(model, extra_field=None, source=None, **filters):
    """
    Get a generator of dicts for the stats model given by the filters.

    Returns {'date': , 'count': } by default. Add an extra field (such as
    application faceting) by passing `extra_field=apps`. `apps` should be in
    the query result.
    """
    extra = () if extra_field is None else (extra_field,)
    # Put a slice on it so we get more than 10 (the default), but limit to 365.
    qs = (
        model.search()
        .order_by('-date')
        .filter(**filters)
        .values_dict('date', 'count', *extra)
    )
    if source:
        qs = qs.source(source)
    for val in qs[:365]:
        # Convert the datetimes to a date.
        date_ = parse(val['date']).date()
        rv = dict(count=val['count'], date=date_, end=date_)
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
    return rv, fields


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


@addon_view
@non_atomic_requests
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
        yield {
            'date': start_date - timedelta(days=idx),
            'data': {'downloads': dl_count, 'updates': up_count},
        }


@addon_view
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


@addon_view
@non_atomic_requests
def sources_series(request, addon, group, start, end, format):
    """Generate download source breakdown."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series(
        DownloadCount, source='sources', addon=addon.id, date__range=date_range
    )

    if format == 'csv':
        series, fields = csv_fields(series)
        return render_csv(
            request, addon, series, ['date', 'count'] + list(fields)
        )
    elif format == 'json':
        return render_json(request, addon, series)


@addon_view
@non_atomic_requests
def usage_series(request, addon, group, start, end, format):
    """Generate ADU counts grouped by ``group`` in ``format``."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series(
        ThemeUserCount if addon.type == amo.ADDON_PERSONA else UpdateCount,
        addon=addon.id,
        date__range=date_range,
    )

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


@addon_view
@non_atomic_requests
def usage_breakdown_series(request, addon, group, start, end, format, field):
    """Generate ADU breakdown of ``field``."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    fields = {
        'applications': 'apps',
        'locales': 'locales',
        'oses': 'os',
        'versions': 'versions',
        'statuses': 'status',
    }
    series = get_series(
        UpdateCount,
        source=fields[field],
        addon=addon.id,
        date__range=date_range,
    )
    if field == 'locales':
        series = process_locales(series)

    if format == 'csv':
        if field == 'applications':
            series = flatten_applications(series)
        series, fields = csv_fields(series)
        return render_csv(
            request, addon, series, ['date', 'count'] + list(fields)
        )
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
                # unicode() to decode the gettext proxy.
                appname = unicode(app.pretty)
                for ver, count in versions.items():
                    key = ' '.join([appname, ver])
                    new[key] = count
            row['data'] = new
        yield row


def process_locales(series):
    """Convert locale codes to pretty names, skip any unknown locales."""
    languages = dict(
        (k.lower(), v['native']) for k, v in product_details.languages.items()
    )
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


def check_stats_permission(request, addon):
    """
    Check if user is allowed to view stats for ``addon``.

    Raises PermissionDenied if user is not allowed.
    """
    can_view = addon.public_stats or (
        request.user.is_authenticated()
        and (
            addon.has_author(request.user)
            or acl.action_allowed(request, amo.permissions.STATS_VIEW)
        )
    )
    if not can_view:
        raise PermissionDenied


@addon_view
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
            'view': view,
            'stats_base_url': stats_base_url,
        },
    )


@non_atomic_requests
def site_stats_report(request, report):
    stats_base_url = reverse('stats.dashboard')
    view = get_report_view(request)
    return render(
        request,
        'stats/reports/%s.html' % report,
        {'report': report, 'view': view, 'stats_base_url': stats_base_url},
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
            'last': str(dates.cleaned_data['last']) + ' days',
        }

    logger.info('Missing "start and end" or "last"')
    return {}


def get_daterange_or_404(start, end):
    """Parse and validate a pair of YYYYMMDD date strings."""
    dates = DateForm(data={'start': start, 'end': end})
    if not dates.is_valid():
        logger.info('Dates parsed were not valid.')
        raise http.Http404

    return (dates.cleaned_data['start'], dates.cleaned_data['end'])


@json_view
@non_atomic_requests
def site_events(request, start, end):
    """Return site events in the given timeframe."""
    start, end = get_daterange_or_404(start, end)
    qs = SiteEvent.objects.filter(
        Q(start__gte=start, start__lte=end) | Q(end__gte=start, end__lte=end)
    )

    events = list(site_event_format(request, qs))

    type_pretty = unicode(amo.SITE_EVENT_CHOICES[amo.SITE_EVENT_RELEASE])

    releases = product_details.firefox_history_major_releases

    for version, date_ in releases.items():
        events.append(
            {
                'start': date_,
                'type_pretty': type_pretty,
                'type': amo.SITE_EVENT_RELEASE,
                'description': 'Firefox %s released' % version,
            }
        )
    return events


def site_event_format(request, events):
    for e in events:
        yield {
            'start': e.start.isoformat(),
            'end': e.end.isoformat() if e.end else None,
            'type_pretty': unicode(amo.SITE_EVENT_CHOICES[e.event_type]),
            'type': e.event_type,
            'description': e.description,
            'url': e.more_info_url,
        }


def daterange(start_date, end_date):
    for n in range((end_date - start_date).days):
        yield start_date + timedelta(n)


# Cached lookup of the keys and the SQL.
# Taken from remora, a mapping of the old values.
_KEYS = {
    'addon_downloads_new': 'addons_downloaded',
    'addon_total_updatepings': 'addons_in_use',
    'addon_count_new': 'addons_created',
    'version_count_new': 'addons_updated',
    'user_count_new': 'users_created',
    'review_count_new': 'reviews_created',
    'collection_count_new': 'collections_created',
}

_CACHED_KEYS = sorted(_KEYS.values())


@memoize(prefix='global_stats', timeout=60 * 60)
def _site_query(period, start, end, field=None, request=None):
    with connection.cursor() as cursor:
        # Let MySQL make this fast. Make sure we prevent SQL injection with the
        # assert.
        if period not in SERIES_GROUPS_DATE:
            raise AssertionError('%s period is not valid.' % period)

        sql = (
            "SELECT name, MIN(date), SUM(count) "
            "FROM global_stats "
            "WHERE date > %%s AND date <= %%s "
            "AND name IN (%s) "
            "GROUP BY %s(date), name "
            "ORDER BY %s(date) DESC;"
            % (', '.join(['%s' for key in _KEYS.keys()]), period, period)
        )
        cursor.execute(sql, [start, end] + _KEYS.keys())

        # Process the results into a format that is friendly for render_*.
        default = {k: 0 for k in _CACHED_KEYS}
        result = OrderedDict()
        for name, date_, count in cursor.fetchall():
            date_ = date_.strftime('%Y-%m-%d')
            if date_ not in result:
                result[date_] = default.copy()
                result[date_]['date'] = date_
                result[date_]['data'] = {}
            result[date_]['data'][_KEYS[name]] = int(count)

    return result.values(), _CACHED_KEYS


@non_atomic_requests
def site(request, format, group, start=None, end=None):
    """Site data from the global_stats table."""
    if not start and not end:
        start = (date.today() - timedelta(days=365)).strftime('%Y%m%d')
        end = date.today().strftime('%Y%m%d')

    group = 'date' if group == 'day' else group
    start, end = get_daterange_or_404(start, end)
    series, keys = _site_query(group, start, end, request)

    if format == 'csv':
        return render_csv(
            request,
            None,
            series,
            ['date'] + keys,
            title='addons.mozilla.org week Site Statistics',
            show_disclaimer=True,
        )

    return render_json(request, None, series)


@login_required
@non_atomic_requests
def collection_report(request, username, slug, report):
    c = get_collection(request, username, slug)
    stats_base_url = c.stats_url()
    view = get_report_view(request)
    return render(
        request,
        'stats/reports/%s.html' % report,
        {
            'collection': c,
            'search_cat': 'collections',
            'report': report,
            'view': view,
            'username': username,
            'slug': slug,
            'stats_base_url': stats_base_url,
        },
    )


@non_atomic_requests
def site_series(request, format, group, start, end, field):
    """Pull a single field from the site_query data"""
    start, end = get_daterange_or_404(start, end)
    group = 'date' if group == 'day' else group
    series = []
    full_series, keys = _site_query(group, start, end, field, request)
    for row in full_series:
        if field in row['data']:
            series.append(
                {'date': row['date'], 'count': row['data'][field], 'data': {}}
            )
    # TODO: (dspasovski) check whether this is the CSV data we really want
    if format == 'csv':
        series, fields = csv_fields(series)
        return render_csv(
            request,
            None,
            series,
            ['date', 'count'] + list(fields),
            title='%s week Site Statistics' % settings.DOMAIN,
            show_disclaimer=True,
        )
    return render_json(request, None, series)


@non_atomic_requests
def collection_series(
    request, username, slug, format, group, start, end, field
):
    """Pull a single field from the collection_query data"""
    start, end = get_daterange_or_404(start, end)
    group = 'date' if group == 'day' else group
    series = []
    c = get_collection(request, username, slug)
    full_series = _collection_query(request, c, start, end)
    for row in full_series:
        if field in row['data']:
            series.append({'date': row['date'], 'count': row['data'][field]})
    return render_json(request, None, series)


@non_atomic_requests
def collection_stats(request, username, slug, group, start, end, format):
    c = get_collection(request, username, slug)
    start, end = get_daterange_or_404(start, end)
    return collection(request, c.uuid, format, start, end)


def _collection_query(request, collection, start=None, end=None):
    if not start and not end:
        start = date.today() - timedelta(days=365)
        end = date.today()

    if not collection.can_view_stats(request):
        raise PermissionDenied

    qs = (
        CollectionCount.search()
        .order_by('-date')
        .filter(id=int(collection.pk), date__range=(start, end))
        .values_dict('date', 'count', 'data')
    )[:365]
    series = []
    for val in qs:
        date_ = parse(val['date']).date()
        series.append(
            dict(
                count=val['count'],
                date=date_,
                end=date_,
                data=extract(val['data']),
            )
        )
    return series


@non_atomic_requests
def collection(request, uuid, format, start=None, end=None):
    collection = get_object_or_404(Collection, uuid=uuid)
    series = _collection_query(request, collection, start, end)
    if format == 'csv':
        series, fields = csv_fields(series)
        return render_csv(
            request, collection, series, ['date', 'count'] + list(fields)
        )
    return render_json(request, collection, series)


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
@non_atomic_requests
def render_csv(
    request, addon, stats, fields, title=None, show_disclaimer=None
):
    """Render a stats series in CSV."""
    # Start with a header from the template.
    ts = time.strftime('%c %z')
    context = {
        'addon': addon,
        'timestamp': ts,
        'title': title,
        'show_disclaimer': show_disclaimer,
    }
    response = render(request, 'stats/csv_header.txt', context)

    writer = UnicodeCSVDictWriter(
        response, fields, restval=0, extrasaction='ignore'
    )
    writer.writeheader()
    writer.writerows(stats)

    fudge_headers(response, stats)
    response['Content-Type'] = 'text/csv; charset=utf-8'
    return response


@allow_cross_site_request
@non_atomic_requests
def render_json(request, addon, stats):
    """Render a stats series in JSON."""
    response = http.HttpResponse(content_type='text/json')

    # Django's encoder supports date and datetime.
    json.dump(stats, response, cls=AMOJSONEncoder)
    fudge_headers(response, response.content != json.dumps([]))
    return response
