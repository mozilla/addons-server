# -*- coding: utf-8 -*-
"""
Generate a summary of a previous loadtest run in this environment.

Output:
    Produces summary on standard output in YAML format.  The structure is as
    follows:

    * monitoring_links:
        * list of link text/url pairs pointing to monitoring dashboards.
    * timeline:
        * begin: ISO 8601 date for when the test began.
        * end: ISO 8601 date for when the test ended.
"""
import re
from urllib import urlencode
from datetime import datetime

import yaml

STANDARD_LOGFILE_PATH = 'logs/loadtests.txt'
LOCUST_TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S,%f'


class NewRelicMonitor(object):
    """
    This class represents the New Relic APM dashboard for a specific app.
    """
    service_name = 'New Relic APM dashboard'

    NEWRELIC_APM_TEMPLATE = 'https://rpm.newrelic.com/accounts/{account_id}/applications/{app_id}'

    def __init__(self, account_name=None, account_id=None, app_name=None, app_id=None,):
        self._account_name = account_name
        self._account_id = account_id
        self._app_name = app_name
        self._app_id = app_id

    @property
    def app_name(self):
        """
        The name of the app being represented by this instance of the
        monitoring service.
        """
        return self._app_name

    def url(self, begin_time=None, end_time=None):
        """
        Generate an APM URL for this app and the given timeframe

        This method is an implementation of the same-signature method in the
        superclass.
        """
        url_without_times = self.NEWRELIC_APM_TEMPLATE.format(
            account_id=self._account_id,
            app_id=self._app_id,
        )
        query_data = {}
        if begin_time:
            # "%s" is the strftime syntax for the number of seconds since
            # the Epoch.
            query_data['tw[start]'] = begin_time.strftime('%s')
            if end_time:
                query_data['tw[end]'] = end_time.strftime('%s')
            else:
                # Due to a race condition in the jenkins job (locust handles
                # SIGTERM after this script gets triggered rather than before),
                # the end_time may not be known yet.  We just assume that the
                # test will be ending soon, so just set the end time to now.
                query_data['tw[end]'] = datetime.now().strftime('%s')
        url = None
        if query_data:
            url = '{}?{}'.format(url_without_times, urlencode(query_data))
        else:
            url = url_without_times
        return url


def parse_logfile_event_marker(line_str):
    match = re.match(
        '\[(.+)\] .+/INFO/.*?: locust event: (.*)$',
        line_str,
    )
    obj = None
    if match:
        timestamp, event = match.group(1, 2)
        obj = {
            # Assume logging is UTC, and return tz-unaware datetime object
            # which implies UTC.
            'time': datetime.strptime(timestamp, LOCUST_TIMESTAMP_FORMAT),
            'event': event,
        }
    return obj


def parse_logfile_events(logfile):
    for line in logfile:
        data = parse_logfile_event_marker(line)
        if data is not None:
            yield (data['time'], data['event'])


def get_time_bounds(logfile):
    """
    Determine when the load test started and stopped.

    Parameters:
        logfile (file): the file containing locust logs for a single load test

    Returns:
        two-tuple of datetime.datetime: the time bounds of the load test
    """
    begin_time = end_time = None
    relevant_events = ['locust_start_hatching', 'quitting']
    relevant_times = [
        time
        for time, event
        in parse_logfile_events(logfile)
        if event in relevant_events
    ]
    begin_time, end_time = (min(relevant_times), max(relevant_times))
    return (begin_time, end_time)


def main():
    """
    Generate a summary of a previous load test run.

    This script assumes "logs/loadtests.txt" is the logfile in question.
    """
    with open(STANDARD_LOGFILE_PATH) as logfile:
        loadtest_begin_time, loadtest_end_time = get_time_bounds(logfile)

    MONITORS = [
        NewRelicMonitor(
            account_name='Mozilla_25',
            account_id='1402187',
            app_name='AMO Loadtests',
            app_id='120750863',
        ),
    ]

    monitoring_links = []
    for monitor in MONITORS:
        monitoring_links.append({
            'url': monitor.url(
                begin_time=loadtest_begin_time,
                end_time=loadtest_end_time,
            ),
            'text': u'{}: {} ({} — {})'.format(
                monitor.service_name,
                monitor.app_name,
                # We use naive datetimes (i.e. no attached tz) and just
                # assume UTC all along.  Tacking on the "Z" implies UTC.
                loadtest_begin_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                loadtest_end_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            ),
        })

    print(yaml.dump(
        {
            'timeline': {
                'begin': loadtest_begin_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'end': loadtest_end_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            },
            'monitoring_links': monitoring_links
        },
        default_flow_style=False,
        allow_unicode=True,
    ))


if __name__ == "__main__":
    main()
