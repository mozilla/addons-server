import cStringIO
import csv
import itertools
import json
import logging
import time
from datetime import date, timedelta
from types import GeneratorType

from django import http
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db.models import Avg, Count, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils.cache import add_never_cache_headers, patch_cache_control
from django.utils.datastructures import SortedDict

from cache_nuggets.lib import memoize
from dateutil.parser import parse
from product_details import product_details

import amo
from access import acl
from addons.decorators import addon_view, addon_view_factory
from addons.models import Addon
from amo.decorators import allow_cross_site_request, json_view, login_required
from amo.urlresolvers import reverse
from bandwagon.models import Collection
from bandwagon.views import get_collection
from zadmin.models import SiteEvent

from .models import (CollectionCount, Contribution, DownloadCount,
                     ThemeUserCount, UpdateCount)


logger = logging.getLogger('z.apps.stats.views')


SERIES_GROUPS = ('day', 'week', 'month')
SERIES_GROUPS_DATE = ('date', 'week', 'month')  # Backwards compat.
SERIES_FORMATS = ('json', 'csv')
SERIES = ('downloads', 'usage', 'contributions', 'overview', 'sources', 'os',
          'locales', 'statuses', 'versions', 'apps')
COLLECTION_SERIES = ('downloads', 'subscribers', 'ratings')
GLOBAL_SERIES = ('addons_in_use', 'addons_updated', 'addons_downloaded',
                 'collections_created', 'reviews_created', 'addons_created',
                 'users_created', 'my_apps')


def dashboard(request):
    stats_base_url = reverse('stats.dashboard')
    view = get_report_view(request)
    return render(request, 'stats/dashboard.html',
                  {'report': 'site', 'view': view,
                   'stats_base_url': stats_base_url})


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
        date_ = parse(val['date'][0]).date()
        rv = dict(count=val['count'][0], date=date_, end=date_)
        if extra_field:
            rv['data'] = extract(val[extra_field])
        if source:
            rv['data'] = extract(val[source])
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

    series = get_series(DownloadCount, source='sources',
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

    series = get_series(
        ThemeUserCount if addon.type == amo.ADDON_PERSONA else UpdateCount,
        addon=addon.id, date__range=date_range)

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
        'applications': 'apps',
        'locales': 'locales',
        'oses': 'os',
        'versions': 'versions',
        'statuses': 'status',
    }
    series = get_series(UpdateCount, source=fields[field],
                        addon=addon.id, date__range=date_range)
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
                # unicode() to decode the gettext proxy.
                appname = unicode(app.pretty)
                for ver, count in versions.items():
                    key = ' '.join([appname, ver])
                    new[key] = count
            row['data'] = new
        yield row


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
    """
    Check if user is allowed to view stats for ``addon``.

    Raises PermissionDenied if user is not allowed.
    """
    # If public, non-contributions: everybody can view.
    if addon.public_stats and not for_contributions:
        return

    # Everything else requires an authenticated user.
    if not request.user.is_authenticated():
        raise PermissionDenied

    if not for_contributions:
        # Only authors and Stats Viewers allowed.
        if (addon.has_author(request.amo_user) or
            acl.action_allowed(request, 'Stats', 'View')):
            return

    else:  # For contribution stats.
        # Only authors and Contribution Stats Viewers.
        if (addon.has_author(request.amo_user) or
            acl.action_allowed(request, 'RevenueStats', 'View')):
            return

    raise PermissionDenied


@addon_view_factory(Addon.objects.valid)
def stats_report(request, addon, report):
    check_stats_permission(request, addon,
                           for_contributions=(report == 'contributions'))
    stats_base_url = reverse('stats.overview', args=[addon.slug])
    view = get_report_view(request)
    return render(request, 'stats/reports/%s.html' % report,
                  {'addon': addon, 'report': report, 'view': view,
                   'stats_base_url': stats_base_url})


def site_stats_report(request, report):
    stats_base_url = reverse('stats.dashboard')
    view = get_report_view(request)
    return render(request, 'stats/reports/%s.html' % report,
                  {'report': report, 'view': view,
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

        return {'range': daterange, 'last': daterange + ' days'}
    else:
        return {}


def get_daterange_or_404(start, end):
    """Parse and validate a pair of YYYYMMDD date strings."""
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


@json_view
def site_events(request, start, end):
    """Return site events in the given timeframe."""
    start, end = get_daterange_or_404(start, end)
    qs = SiteEvent.objects.filter(
        Q(start__gte=start, start__lte=end) |
        Q(end__gte=start, end__lte=end))

    events = list(site_event_format(request, qs))

    type_pretty = unicode(amo.SITE_EVENT_CHOICES[amo.SITE_EVENT_RELEASE])

    releases = product_details.firefox_history_major_releases

    for version, date in releases.items():
        events.append({
            'start': date,
            'type_pretty': type_pretty,
            'type': amo.SITE_EVENT_RELEASE,
            'description': 'Firefox %s released' % version,
        })
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


# TODO: (dspasovski) - remove this once we know the indexed stats return JSON
@json_view
def fake_collection_stats(request, username, slug, group, start, end, format):
    from time import strftime
    from math import sin, floor
    start, end = check_series_params_or_404(group, start, end, format)
    faked = []
    val = 0
    for single_date in daterange(start, end):
        isodate = strftime("%Y-%m-%d", single_date.timetuple())
        faked.append({
         'date': isodate,
         'count': floor(200 + 50 * sin(val + 1)),
         'data': {
            'downloads': floor(200 + 50 * sin(2 * val + 2)),
            'votes_up': floor(200 + 50 * sin(3 * val + 3)),
            'votes_down': floor(200 + 50 * sin(4 * val + 4)),
            'subscribers': floor(200 + 50 * sin(5 * val + 5)),
        }})
        val += .01
    return faked


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


@memoize(prefix='global_stats', time=60 * 60)
def _site_query(period, start, end, field=None, request=None):

    cursor = connection.cursor()
    # Let MySQL make this fast. Make sure we prevent SQL injection with the
    # assert.
    if period not in SERIES_GROUPS_DATE:
        raise AssertionError('%s period is not valid.' % period)

    sql = ("SELECT name, MIN(date), SUM(count) "
           "FROM global_stats "
           "WHERE date > %%s AND date <= %%s "
           "AND name IN (%s) "
           "GROUP BY %s(date), name "
           "ORDER BY %s(date) DESC;"
           % (', '.join(['%s' for key in _KEYS.keys()]), period, period))
    cursor.execute(sql, [start, end] + _KEYS.keys())

    # Process the results into a format that is friendly for render_*.
    default = dict([(k, 0) for k in _CACHED_KEYS])
    result = SortedDict()
    for name, date, count in cursor.fetchall():
        date = date.strftime('%Y-%m-%d')
        if date not in result:
            result[date] = default.copy()
            result[date]['date'] = date
            result[date]['data'] = {}
        result[date]['data'][_KEYS[name]] = int(count)

    return result.values(), _CACHED_KEYS


def site(request, format, group, start=None, end=None):
    """Site data from the global_stats table."""
    if not start and not end:
        start = (date.today() - timedelta(days=365)).strftime('%Y%m%d')
        end = date.today().strftime('%Y%m%d')

    group = 'date' if group == 'day' else group
    start, end = get_daterange_or_404(start, end)
    series, keys = _site_query(group, start, end, request)

    if format == 'csv':
        return render_csv(request, None, series, ['date'] + keys,
                          title='addons.mozilla.org week Site Statistics',
                          show_disclaimer=True)

    return render_json(request, None, series)


@login_required
def collection_report(request, username, slug, report):
    c = get_collection(request, username, slug)
    stats_base_url = c.stats_url()
    view = get_report_view(request)
    return render(request, 'stats/reports/%s.html' % report,
                  {'collection': c, 'search_cat': 'collections',
                   'report': report, 'view': view, 'username': username,
                   'slug': slug, 'stats_base_url': stats_base_url})


def site_series(request, format, group, start, end, field):
    """Pull a single field from the site_query data"""
    start, end = get_daterange_or_404(start, end)
    group = 'date' if group == 'day' else group
    series = []
    full_series, keys = _site_query(group, start, end, field, request)
    for row in full_series:
        if field in row['data']:
            series.append({
                'date': row['date'],
                'count': row['data'][field],
                'data': {},
            })
    # TODO: (dspasovski) check whether this is the CSV data we really want
    if format == 'csv':
        series, fields = csv_fields(series)
        return render_csv(request, None, series,
                          ['date', 'count'] + list(fields),
                          title='%s week Site Statistics' % settings.DOMAIN,
                          show_disclaimer=True)
    return render_json(request, None, series)


def collection_series(request, username, slug, format, group, start, end,
                      field):
    """Pull a single field from the collection_query data"""
    start, end = get_daterange_or_404(start, end)
    group = 'date' if group == 'day' else group
    series = []
    c = get_collection(request, username, slug)
    full_series = _collection_query(request, c, start, end)
    for row in full_series:
        if field in row['data']:
            series.append({
                'date': row['date'],
                'count': row['data'][field],
            })
    return render_json(request, None, series)


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

    qs = (CollectionCount.search().order_by('-date')
                         .filter(id=int(collection.pk),
                                 date__range=(start, end))
                         .values_dict())[:365]
    series = []
    for val in qs:
        date_ = parse(val['date']).date()
        series.append(dict(count=val['count'], date=date_, end=date_,
                           data=extract(val['data'])))
    return series


def collection(request, uuid, format, start=None, end=None):
    collection = get_object_or_404(Collection, uuid=uuid)
    series = _collection_query(request, collection, start, end)
    if format == 'csv':
        series, fields = csv_fields(series)
        return render_csv(request, collection, series,
                          ['date', 'count'] + list(fields))
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
def render_csv(request, addon, stats, fields,
               title=None, show_disclaimer=None):
    """Render a stats series in CSV."""
    # Start with a header from the template.
    ts = time.strftime('%c %z')
    context = {'addon': addon, 'timestamp': ts, 'title': title,
               'show_disclaimer': show_disclaimer}
    response = render(request, 'stats/csv_header.txt', context)

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
    json.dump(stats, response, cls=DjangoJSONEncoder)
    return response
