import time
from datetime import date, timedelta

import jingo

from addons.decorators import addon_view, addon_view_factory
from addons.models import Addon

import amo
from amo.decorators import json_view
from amo.urlresolvers import reverse

# Reuse Potch's box of magic.
from stats.models import DownloadCount
from stats.views import (check_series_params_or_404, check_stats_permission,
                         daterange, get_report_view, get_series, render_json,
                         SERIES_GROUPS, SERIES_GROUPS_DATE, SERIES_FORMATS)

# Most of these are not yet available.
SERIES = ('active', 'devices', 'installs', 'app_overview', 'referrers', 'sales',
          'usage')


@addon_view_factory(Addon.objects.valid)
def stats_report(request, addon, report):
    check_stats_permission(request, addon)
    stats_base_url = reverse('mkt.stats.overview', args=[addon.app_slug])
    view = get_report_view(request)
    return jingo.render(request, 'appstats/reports/%s.html' % report,
                        {'addon': addon,
                         'report': report,
                         'view': view,
                         'stats_base_url': stats_base_url})


#TODO: This view will require some complex JS logic similar to apps/stats.
@addon_view
def overview_series(request, addon, group, start, end, format):
    """Combines installs_series and usage_series into one payload."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    dls = get_series(DownloadCount, addon=addon.id, date__range=date_range)

    # Uncomment the line below to return fake stats.
    return fake_app_stats(request, addon, group, start, end, format)

    return render_json(request, addon, dls)


#TODO: Real stats data needs to be plugged in.
@addon_view
def sales_series(request, addon, group, start, end, format):
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series(DownloadCount, addon=addon.id, date__range=date_range)

    # Uncomment the line below to return fake stats.
    return fake_app_stats(request, addon, group, start, end, format)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)



#TODO: Real stats data needs to be plugged in.
@addon_view
def installs_series(request, addon, group, start, end, format):
    """Generate install counts grouped by ``group`` in ``format``."""
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series(DownloadCount, addon=addon.id, date__range=date_range)

    # Uncomment the line below to return fake stats.
    return fake_app_stats(request, addon, group, start, end, format)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


#TODO: Real stats data needs to be plugged in.
@addon_view
def usage_series(request, addon, group, start, end, format):
    date_range = check_series_params_or_404(group, start, end, format)
    check_stats_permission(request, addon)

    series = get_series(DownloadCount, addon=addon.id, date__range=date_range)

    # Uncomment the line below to return fake stats.
    return fake_app_stats(request, addon, group, start, end, format)

    if format == 'csv':
        return render_csv(request, addon, series, ['date', 'count'])
    elif format == 'json':
        return render_json(request, addon, series)


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
            'sales': floor(200 + 50 * sin(4 * val + 4)),
            #'device': floor(200 + 50 * sin(5 * val + 5)),
        }})
        val += .01
    return faked
