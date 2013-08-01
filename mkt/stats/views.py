import datetime
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import logging

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

import jingo
from waffle.decorators import waffle_switch
import waffle

from access import acl
import amo
from amo.decorators import json_view, login_required, permission_required
from amo.urlresolvers import reverse
from lib.metrics import get_monolith_client
from mkt.inapp_pay.models import InappPayment
from mkt.webapps.decorators import app_view, app_view_factory
from mkt.webapps.models import Installed, Webapp
from stats.models import Contribution, UpdateCount
from stats.views import (check_series_params_or_404, daterange,
                         get_report_view, render_csv, render_json)


logger = logging.getLogger('z.mkt.stats.views')
FINANCE_SERIES = (
    'sales', 'refunds', 'revenue',
    'currency_revenue', 'currency_sales', 'currency_refunds',
    'source_revenue', 'source_sales', 'source_refunds',
    'revenue_inapp', 'sales_inapp', 'refunds_inapp',
    'currency_revenue_inapp', 'currency_sales_inapp',
    'currency_refunds_inapp', 'source_revenue_inapp',
    'source_sales_inapp', 'source_refunds_inapp'
)
SERIES = FINANCE_SERIES + ('installs', 'usage', 'my_apps')
SERIES_GROUPS = ('day', 'week', 'month')
SERIES_GROUPS_DATE = ('date', 'week', 'month')
SERIES_FORMATS = ('json', 'csv')


@app_view_factory(Webapp.objects.all)
def stats_report(request, addon, report, inapp=None, category_field=None):
    """
    Stats page. Passes in context variables into template which is read by the
    JS to build a URL. The URL calls a *_series view which determines
    necessary arguments for get_series_*. get_series_* queries ES for the data,
    which is later formatted into .json or .csv and made available to the JS.
    """
    if (addon.status is not amo.STATUS_PUBLIC and
        not check_stats_permission(request, addon, for_contributions=True,
                                   no_raise=True)):
        return redirect(addon.get_detail_url())
    check_stats_permission(request, addon)

    # For inapp, point template to same as non-inapp, but still use
    # different report names.
    template_name = 'appstats/reports/%s.html' % report.replace('_inapp', '')
    if inapp:
        stats_base_url = addon.get_stats_inapp_url(action='revenue',
                                                   inapp=inapp)
    else:
        stats_base_url = reverse('mkt.stats.overview', args=[addon.app_slug])
    view = get_report_view(request)

    # Get list of in-apps for drop-down in-app selector.
    inapps = []
    # Until we figure out why ES stores strings in lowercase despite
    # the field being set to not analyze, we grab the lowercase version
    # from ES and do a case-insensitive query to the ORM to un-lowercase.
    inapps_lower = list(set(payment['inapp'] for payment in list(
        InappPayment.search().filter(
        addon=addon.id).values_dict('inapp'))))
    for inapp_name in inapps_lower:
        inapps.append(InappPayment.objects.filter(
            name__iexact=inapp_name)[0].name)

    return jingo.render(request, template_name, {
        'addon': addon,
        'report': report,
        'view': view,
        'stats_base_url': stats_base_url,
        'inapp': inapp,
        'inapps': inapps,
    })


@login_required
@waffle_switch('developer-stats')
def my_apps_report(request, report):
    """
    A report for a developer, showing multiple apps.
    """
    view = get_report_view(request)
    template_name = 'devstats/reports/%s.html' % report
    return jingo.render(request, template_name, {
        'view': view,
        'report': 'my_apps',
    })


def get_series_line(model, group, primary_field=None, extra_fields=None,
                    extra_values=None, **filters):
    """
    Get a generator of dicts for the stats model given by the filters, made
    to fit into Highchart's datetime line graph.

    primary_field takes a field name that can be referenced by the key 'count'
    extra_fields takes a list of fields that can be found in the index
    on top of date and count and can be seen in the output
    extra_values is a list of constant values added to each line
    """
    if not extra_fields:
        extra_fields = []

    extra_values = extra_values or {}

    if waffle.switch_is_active('monolith-stats'):
        keys = {Installed: 'app_installs',
                UpdateCount: 'updatecount_XXX',
                Contribution: 'contribution_XXX',
                InappPayment: 'inapppayment_XXX'}

        # Getting data from the monolith server.
        client = get_monolith_client()

        field = keys[model]
        start, end = filters['date__range']

        if group == 'date':
            group = 'day'

        try:
            for result in client(field, start, end, interval=group,
                                 addon_id=filters['addon']):
                res = {'count': result['count']}
                for extra_field in extra_fields:
                    res[extra_field] = result[extra_field]
                date_ = date(*result['date'].timetuple()[:3])
                res['end'] = res['date'] = date_
                res.update(extra_values)
                yield res
        except ValueError as e:
            if len(e.args) > 0:
                logger.error(e.args[0])

    else:
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
        data += pad_missing_stats(days, group, filters.get('date__range'),
                                  fields)

        # Sort in descending order.
        data = sorted(data, key=lambda document: document['date'],
                      reverse=True)

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
            rv.update(extra_values)
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
    # Differentiates what we query the ORM and ES with. Set up ORM query.
    if model == InappPayment and 'name' in filters:
        category_field = 'contribution__' + category_field

    categories = list(set(model.objects.filter(**filters).values_list(
                          category_field, flat=True)))

    # Set up ES query.
    if model == InappPayment and filters['name']:
        category_field = category_field.replace('contribution__', '')
    if 'name' in filters:
        filters['inapp'] = filters['name']
        del(filters['name'])
    if 'config__addon' in filters:
        filters['addon'] = filters['config__addon']
        del(filters['config__addon'])

    data = []
    for category in categories:
        # Have to query ES in lower-case.
        try:
            category = category.lower()
        except AttributeError:
            pass

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
@app_view
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


@app_view
def installs_series(request, addon, group, start, end, format):
    """
    Generate install counts grouped by ``group`` in ``format``.
    """
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series_line(Installed, group, addon=addon.id,
                             date__range=date_range)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


def _my_apps(request):
    """
    Find the apps you are allowed to see stats for, by getting all apps
    and then filtering down.
    """
    filtered = []
    if not getattr(request, 'amo_user', None):
        return filtered

    addon_users = (request.amo_user.addonuser_set
                          .filter(addon__type=amo.ADDON_WEBAPP)
                          .exclude(addon__status=amo.STATUS_DELETED))
    for addon_user in addon_users:
        if check_stats_permission(request, addon_user.addon, no_raise=True):
            filtered.append(addon_user.addon)
    return filtered


def my_apps_series(request, group, start, end, format):
    """
    Install counts for multiple apps. This is a temporary hack that will
    probably live forever.
    """
    date_range = check_series_params_or_404(group, start, end, format)
    apps = _my_apps(request)
    series = []
    for app in apps:
        # The app name is going to appended in slightly different ways
        # depending upon data format.
        if format == 'csv':
            series = get_series_line(Installed, group, addon=app.id,
                                     date__range=date_range,
                                     extra_values={'name': (app.name)})
        elif format == 'json':
            data = get_series_line(Installed, group, addon=app.id,
                                   date__range=date_range)
            series.append({'name': str(app.name), 'data': list(data)})

    if format == 'csv':
        return render_csv(request, apps, series, ['name', 'date', 'count'])
    elif format == 'json':
        return render_json(request, apps, series)


#TODO: real data
@app_view
def usage_series(request, addon, group, start, end, format):
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series_line(UpdateCount, group, addon=addon.id,
                             date__range=date_range)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


@app_view
def finance_line_series(request, addon, group, start, end, format,
                        primary_field=None, inapp=None):
    """
    Date-based contribution series.
    primary_field -- revenue/count/refunds
    inapp -- inapp name, which shows stats for a certain inapp
    """
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon, for_contributions=True)

    if inapp:
        series = get_series_line(InappPayment, group,
            primary_field=primary_field, addon=addon.id,
            date__range=date_range, inapp=inapp.lower())
    else:
        series = get_series_line(Contribution, group,
            primary_field=primary_field, addon=addon.id,
            date__range=date_range)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


@app_view
def finance_column_series(request, addon, group, start, end, format,
                          primary_field=None, category_field=None,
                          inapp=None):
    """
    Non-date-based contribution series, column graph.
    primary_field -- revenue/count/refunds
    category_field -- breakdown field, currency/source
    inapp -- inapp name, which shows stats for a certain inapp
    """
    check_stats_permission(request, addon, for_contributions=True)

    if not inapp:
        series = get_series_column(Contribution, primary_field=primary_field,
            category_field=category_field, addon=addon.id)
    else:
        series = get_series_column(InappPayment, primary_field=primary_field,
            category_field=category_field, config__addon=addon.id,
            name=inapp.lower())

    # Since we're currently storing everything in lower-case in ES,
    # re-capitalize the currency.
    if category_field == 'currency':
        series = list(series)
        for datum in series:
            datum['currency'] = datum['currency'].upper()

    if format == 'csv':
        return render_csv(request, addon, series, [category_field, 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


def check_stats_permission(request, addon, for_contributions=False,
                           no_raise=False):
    """
    Check if user is allowed to view stats for ``addon``.

    no_raise -- if enabled function returns true or false
                else function raises PermissionDenied
                if user is not allowed.
    """
    # If public, non-contributions: everybody can view.
    if addon.public_stats and not for_contributions:
        return True

    # Everything else requires an authenticated user.
    if not request.user.is_authenticated():
        if no_raise:
            return False
        raise PermissionDenied

    if not for_contributions:
        # Only authors and Stats Viewers allowed.
        if (addon.has_author(request.amo_user) or
            acl.action_allowed(request, 'Stats', 'View')):
            return True

    else:  # For contribution stats.
        # Only authors and Contribution Stats Viewers.
        if (addon.has_author(request.amo_user) or
            acl.action_allowed(request, 'RevenueStats', 'View')):
            return True

    if no_raise:
        return False
    raise PermissionDenied


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


@permission_required('Stats', 'View')
def overall(request, report):
    view = get_report_view(request)
    return jingo.render(request, 'sitestats/stats.html', {'report': report,
                                                          'view': view})
