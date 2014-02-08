import datetime
import json
import uuid
from collections import namedtuple

import mock
from nose.tools import eq_, ok_

from django.core.urlresolvers import reverse
from django.test import client

from amo.tests import TestCase
from mkt.api.tests.test_oauth import RestOAuth
from mkt.site.fixtures import fixture

from .models import MonolithRecord, record_stat
from .resources import daterange


class RequestFactory(client.RequestFactory):

    def __init__(self, session_key=None, user_agent=None,
                 remote_addr=None, anonymous=True, *args, **kwargs):

        class User(object):
            def is_anonymous(self):
                return anonymous

        Session = namedtuple('Session', 'session_key')
        self.session = Session(session_key or str(uuid.uuid1()))
        self.user = User()
        self.META = {}
        if remote_addr:
            self.META['REMOTE_ADDR'] = remote_addr
        if user_agent:
            self.META['User-Agent'] = user_agent

        super(RequestFactory, self).__init__(*args, **kwargs)


def total_seconds(td):
    # not present in 2.6
    return ((td.microseconds + (td.seconds + td.days * 24 * 3600) * 10 ** 6) /
            10 ** 6)


class TestModels(TestCase):

    def setUp(self):
        super(TestModels, self).setUp()
        self.request = RequestFactory()

    def test_record_stat(self):
        now = datetime.datetime.utcnow()
        record_stat('app.install', self.request, value=1)

        # we should have only one record
        record = MonolithRecord.objects.get()

        eq_(record.key, 'app.install')
        eq_(record.value, json.dumps({'value': 1}))
        self.assertTrue(total_seconds(record.recorded - now) < 1)

    def test_record_stat_without_data(self):
        with self.assertRaises(ValueError):
            record_stat('app.install', self.request)


class TestMonolithResource(RestOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestMonolithResource, self).setUp()
        self.grant_permission(self.profile, 'Monolith:API')
        self.list_url = reverse('monolith-list')
        self.now = datetime.datetime(2013, 02, 12, 17, 34)
        self.last_month = self.now - datetime.timedelta(days=30)
        self.last_week = self.now - datetime.timedelta(days=7)
        self.yesterday = self.now - datetime.timedelta(days=1)
        self.date_format = '%Y-%m-%d'
        self.request = RequestFactory()

    def test_normal_call_with_no_records(self):
        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)

        eq_(data['objects'], [])

    def test_normal_call(self):
        record_stat('app.install', self.request, value=2)

        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)

        eq_(len(data['objects']), 1)
        obj = data['objects'][0]

        eq_(obj['key'], 'app.install')
        eq_(obj['value'], {'value': 2})

        # Check other fields we want to exist but ignore their value here.
        for field in ('recorded', 'user_hash'):
            assert field in obj

    def test_filter_by_date(self):
        for id_, date in enumerate((self.last_week, self.yesterday, self.now)):
            record_stat('app.install', self.request, __recorded=date,
                        value=id_)

        res = self.client.get(self.list_url, data={
            'end': self.now.strftime(self.date_format)})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 2)

        res = self.client.get(self.list_url, data={
            'start': self.yesterday.strftime(self.date_format),
            'end': self.now.strftime(self.date_format)})
        data = json.loads(res.content)
        eq_(len(data['objects']), 1)

    def test_filter_by_key(self):
        record_stat('apps_added_us_free', self.request, value=3)
        record_stat('apps_added_uk_free', self.request, value=1)

        # Exact match.
        res = self.client.get(self.list_url,
                              data={'key': 'apps_added_us_free'})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 1)

    @mock.patch('mkt.monolith.resources._get_query_result')
    def test_on_the_fly_query(self, _get_query):
        key = 'apps_total_ratings'
        _get_query.return_value = [{
            'key': key,
            'recorded': datetime.date.today(),
            'user_hash': None,
            'value': {'count': 1, 'app-id': 123}}]

        res = self.client.get(self.list_url, data={'key': key})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 1)

        obj = data['objects'][0]
        eq_(obj['key'], key)
        eq_(obj['recorded'], datetime.date.today().strftime(self.date_format))
        eq_(obj['value']['count'], 1)
        eq_(obj['value']['app-id'], 123)

    def test_on_the_fly_missing_start(self):
        key = 'apps_total_ratings'
        res = self.client.get(self.list_url, data={'key': key})
        eq_(res.status_code, 400)
        data = json.loads(res.content)
        eq_(data['detail'], '`start` was not provided')

    @mock.patch('mkt.monolith.resources._get_query_result')
    def test_on_the_fly_query_pagination(self, _get_query):
        key = 'apps_total_ratings'
        _get_query.return_value = [
            {'key': key, 'recorded': datetime.date.today(), 'user_hash': None,
             'value': {'count': 1, 'app-id': 123}},
            {'key': key, 'recorded': datetime.date.today(), 'user_hash': None,
             'value': {'count': 1, 'app-id': 234}},
            {'key': key, 'recorded': datetime.date.today(), 'user_hash': None,
             'value': {'count': 1, 'app-id': 345}},
        ]

        res = self.client.get(self.list_url, data={'key': key, 'limit': 2})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 2)

        ok_(data['meta']['next'] is not None)
        ok_(data['meta']['previous'] is None)
        eq_(data['meta']['total_count'], 3)
        eq_(data['meta']['offset'], 0)
        eq_(data['meta']['limit'], 2)

        eq_(data['objects'][0]['value']['app-id'], 123)
        eq_(data['objects'][1]['value']['app-id'], 234)

        res = self.client.get(self.list_url, data={'key': key, 'limit': 2,
                                                   'offset': 2})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 1)
        eq_(data['objects'][0]['value']['app-id'], 345)

        ok_(data['meta']['next'] is None)
        ok_(data['meta']['previous'] is not None)
        eq_(data['meta']['total_count'], 3)
        eq_(data['meta']['offset'], 2)
        eq_(data['meta']['limit'], 2)

    def test_pagination(self):
        record_stat('app.install', self.request, value=2)
        record_stat('app.install', self.request, value=4)
        record_stat('app.install', self.request, value=6)

        res = self.client.get(self.list_url, data={'limit': 2})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 2)

        ok_(data['meta']['next'] is not None)
        ok_(data['meta']['previous'] is None)
        eq_(data['meta']['total_count'], 3)
        eq_(data['meta']['offset'], 0)
        eq_(data['meta']['limit'], 2)


class TestDateRange(TestCase):

    def setUp(self):
        self.today = datetime.datetime.now().replace(microsecond=0)
        self.week_ago = self.days_ago(7)

    def test_date_range(self):
        range = list(daterange(self.week_ago, self.today))
        eq_(len(range), 8)  # Dates are inclusive.
        eq_(range[0], self.week_ago)
        eq_(range[-1], self.today)
