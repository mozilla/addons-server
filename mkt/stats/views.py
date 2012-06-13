import datetime
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

import jingo

from addons.decorators import addon_view, addon_view_factory
from addons.models import Addon
from amo.decorators import json_view
from amo.urlresolvers import reverse
from mkt.webapps.models import Installed
from stats.models import Contribution, UpdateCount
from stats.views import (check_series_params_or_404, check_stats_permission,
                         get_report_view, render_csv, render_json, daterange)

SERIES = ('installs', 'usage', 'revenue', 'sales', 'refunds',
          'currency_revenue', 'currency_sales', 'currency_refunds',
          'source_revenue', 'source_sales', 'source_refunds')
SERIES_GROUPS = ('day', 'week', 'month')
SERIES_GROUPS_DATE = ('date', 'week', 'month')
SERIES_FORMATS = ('json', 'csv')


@addon_view_factory(Addon.objects.valid)
def stats_report(request, addon, report):
    check_stats_permission(request, addon)
    stats_base_url = reverse('mkt.stats.overview', args=[addon.app_slug])
    view = get_report_view(request)
    return jingo.render(request, 'appstats/reports/%s.html' % report,
                        {'addon': addon,
                         'report': report,
                         'view': view,
                         'stats_base_url': stats_base_url,
                        })


def get_series_line(model, group, primary_field=None, extra_fields=None,
                    **filters):
    """
    Get a generator of dicts for the stats model given by the filters, made
    to fit into Highchart's datetime line graph.

    primary_field takes a field name that can be referenced by the key 'count'
    extra_fields takes a list of fields that can be found in the index
    on top of date and count and can be seen in the output
    """
    if not extra_fields:
        extra_fields = []

    # Pull data out of ES
    data = list((model.search().order_by('-date').filter(**filters)
          .values_dict('date', 'count', primary_field, *extra_fields))[:365])

    # Pad empty data with dummy dicts.
    days = [datum['date'].date() for datum in data]
    fields = []
    if primary_field:
        fields.append(primary_field)
    if extra_fields:
        fields += extra_fields
    data += pad_missing_stats(days, group, filters.get('date__range'), fields)

    # Sort in descending order.
    data = sorted(data, key=lambda document: document['date'], reverse=True)

    # Generate dictionary with options from ES document
    for val in data:
        # Convert the datetimes to a date.
        date_ = date(*val['date'].timetuple()[:3])
        if primary_field and primary_field != 'count':
            rv = dict(count=val[primary_field], date=date_, end=date_)
        else:
            rv = dict(count=val['count'], date=date_, end=date_)
        for extra_field in extra_fields:
            rv[extra_field] = val[extra_field]
        yield rv


def get_series_column(model, primary_field=None, category_field=None,
                      **filters):
    """
    Get a generator of dicts for the stats model given by the filters, made
    to fit into Highchart's column graph.

    primary_field  -- field name that is converted into generic key 'count'.
    category_field -- the breakdown field for x-axis (e.g. currency, source),
                      is a Highcharts term where categories are the xAxis
                      values.
    """
    categories = list(set(model.objects.filter(**filters).values_list(
                          category_field, flat=True)))

    data = []
    for category in categories:
        # Have to query ES in lower-case.
        category = category.lower()

        filters[category_field] = category
        if primary_field:
            data += list((model.search().filter(**filters)
                          .values_dict(category_field, 'count',
                                       primary_field)))
        else:
            data += list((model.search().filter(**filters)
                          .values_dict(category_field, 'count')))
        del(filters[category_field])

    # Sort descending.
    if primary_field:
        data = sorted(data, key=lambda datum: datum.get(primary_field),
                      reverse=True)
    else:
        data = sorted(data, key=lambda datum: datum['count'], reverse=True)

    # Generate dictionary.
    for val in data:
        if primary_field:
            rv = dict(count=val[primary_field])
        else:
            rv = dict(count=val['count'])
        if category_field:
            rv[category_field] = val[category_field]
            # Represent empty strings as 'N/A' in the frontend.
            if not rv[category_field]:
                rv[category_field] = 'N/A'
        yield rv


#TODO: complex JS logic similar to apps/stats, real stats data
@addon_view
def overview_series(request, addon, group, start, end, format):
    """
    Combines installs_series and usage_series into one payload.
    """
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series_line(Installed, group, addon=addon.id,
                             date__range=date_range)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


@addon_view
def installs_series(request, addon, group, start, end, format):
    """Generate install counts grouped by ``group`` in ``format``."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series_line(Installed, group, addon=addon.id,
                             date__range=date_range)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


#TODO: real data
@addon_view
def usage_series(request, addon, group, start, end, format):
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series_line(UpdateCount, group, addon=addon.id,
                             date__range=date_range)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


@addon_view
def revenue_series(request, addon, group, start, end, format):
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon, for_contributions=True)

    series = get_series_line(Contribution, group, primary_field='revenue',
                             addon=addon.id, date__range=date_range)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


@addon_view
def sales_series(request, addon, group, start, end, format):
    """
    Sequel to contribution series
    """
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon, for_contributions=True)

    series = get_series_line(Contribution, group, addon=addon.id,
                             date__range=date_range)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


@addon_view
def refunds_series(request, addon, group, start, end, format):
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon, for_contributions=True)

    series = get_series_line(Contribution, group, primary_field='refunds',
                             addon=addon.id, date__range=date_range)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


@addon_view
def currency_series(request, addon, group, start, end, format,
                    primary_field=None):
    check_stats_permission(request, addon, for_contributions=True)

    series = get_series_column(Contribution, primary_field=primary_field,
                               category_field='currency', addon=addon.id)

    # Since we're currently storing everything in lower-case in ES,
    # re-capitalize the currency.
    series = list(series)
    for datum in series:
        datum['currency'] = datum['currency'].upper()

    if format == 'csv':
        return render_csv(request, addon, series, ['currency', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


@addon_view
def source_series(request, addon, group, start, end, format,
                  primary_field=None):
    check_stats_permission(request, addon, for_contributions=True)

    series = get_series_column(Contribution, primary_field=primary_field,
                               category_field='source', addon=addon.id)

    if format == 'csv':
        return render_csv(request, addon, series, ['source', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


def pad_missing_stats(days, group, date_range=None, fields=None):
    """
    Bug 758480: return dummy dicts with values of 0 to pad missing dates
    days -- list of datetime dates that have returned data
    group -- grouping by day, week, or month
    date_range -- optional, to extend the padding to fill a date range
    fields -- fields to insert into the dummy dict with values of 0
    """
    if not fields:
        fields = []

    # Add 0s for missing daily stats (so frontend represents empty stats as 0).
    days = sorted(set(days))

    # Make sure whole date range is padded so data doesn't just start at first
    # data point returned from ES.
    if date_range:
        start, end = date_range
        if start not in days:
            days.insert(0, start)
        if end not in days:
            days.append(end)

    if group == 'day':
        max_delta = timedelta(1)
        group_delta = relativedelta(days=1)
    elif group == 'week':
        max_delta = timedelta(7)
        group_delta = relativedelta(weeks=1)
    elif group == 'month':
        max_delta = timedelta(31)
        group_delta = relativedelta(months=1)

    dummy_dicts = []
    for day in enumerate(days):
        # Find missing dates between two dates in the list of days.
        try:
            # Pad based on the group (e.g don't insert days in a week view).
            if days[day[0] + 1] - day[1] > max_delta:
                dummy_date = day[1] + group_delta
                dummy_dict = {
                    'date': datetime.datetime.combine(dummy_date,
                                                      datetime.time(0, 0)),
                    'count': 0
                }

                for field in fields:
                    dummy_dict[field] = 0

                # Insert dummy day into current iterated list to find more
                # empty spots.
                days.insert(day[0] + 1, dummy_date)
                dummy_dicts.append(dummy_dict)
        except IndexError:
            break
    return dummy_dicts


def dbg(s):
    """
    Debug information to a file, useful to debug ajax functions (get_series)
    """
    open('debug', 'a').write('\n' + str(s) + '\n')


@json_view
def fake_app_stats(request, addon, group, start, end, format):
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
            'installs': floor(200 + 50 * sin(2 * val + 2)),
            'usage': floor(200 + 50 * sin(3 * val + 3)),
            #'device': floor(200 + 50 * sin(5 * val + 5)),
        }})
        val += .01
    return faked
