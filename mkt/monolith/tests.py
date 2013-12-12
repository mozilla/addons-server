import datetime
import json
import uuid
from collections import namedtuple

from nose.tools import eq_

from django.core.urlresolvers import reverse
from django.test import client

from amo.tests import TestCase
from mkt.api.tests.test_oauth import RestOAuth
from mkt.site.fixtures import fixture

from .models import MonolithRecord, record_stat


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
        for field in ('id', 'recorded', 'user_hash'):
            assert field in obj

    def test_filter_by_date(self):
        for id_, date in enumerate((self.last_week, self.yesterday, self.now)):
            record_stat('app.install', self.request, __recorded=date,
                        value=id_)

        res = self.client.get(self.list_url,
                              data={'recorded__lte': self.now.isoformat()})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 3)

        res = self.client.get(
                self.list_url,
                data={'recorded__gte': self.yesterday.isoformat(),
                      'recorded__lte': self.now.isoformat()})
        data = json.loads(res.content)
        eq_(len(data['objects']), 2)

    def test_filter_by_key(self):
        record_stat('apps_added_us_free', self.request, value=3)
        record_stat('apps_added_uk_free', self.request, value=1)

        # Exact match.
        res = self.client.get(self.list_url,
                              data={'key': 'apps_added_us_free'})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 1)

    def test_deletion_by_filtering(self):
        # We should be able to delete a set of items using the API.
        for id_, date in enumerate((self.last_month, self.last_week,
                                    self.yesterday, self.now)):
            record_stat('app.install', self.request, __recorded=date,
                        value=id_)

        eq_(MonolithRecord.objects.count(), 4)

        res = self.client.delete(self.list_url,
                                 data={'start': self.last_week,
                                       'end': self.now})
        eq_(res.status_code, 204)
        eq_(list(MonolithRecord.objects.values_list('recorded', flat=True)),
            [self.last_month, self.now])

    def test_deletion_by_filtering_old(self):
        for id_, date in enumerate((self.last_month, self.last_week
                                    , self.yesterday, self.now)):
            record_stat('app.install', self.request, __recorded=date,
                        value=id_)

        eq_(MonolithRecord.objects.count(), 4)

        res = self.client.delete(self.list_url,
                                 data={'recorded__gte': self.last_week,
                                       'recorded__lt': self.now})
        eq_(res.status_code, 204)
        eq_(list(MonolithRecord.objects.values_list('recorded', flat=True)),
            [self.last_month, self.now])


    def test_deletion_by_id(self):
        record_stat('app.install', self.request, __recorded=self.now, value=1)
        records = MonolithRecord.objects.all()
        eq_(len(records), 1)

        url = reverse('monolith-detail', args=(records[0].pk,))
        res = self.client.delete(url)

        eq_(res.status_code, 204)
        eq_(MonolithRecord.objects.count(), 0)

    def test_deletion_by_date(self):
        for date in (self.last_month, self.last_week, self.yesterday,
                     self.now):
            record_stat('app.install', self.request, __recorded=date, value=1)
            record_stat('foo.bar', self.request, __recorded=date, value=1)
        res = self.client.delete(self.list_url, data={
            'recorded__gte': self.last_week.isoformat(),
            'recorded__lt': self.now.isoformat(),
            'key': 'app.install'})

        eq_(res.status_code, 204)
        eq_(MonolithRecord.objects.count(), 6)

        res = self.client.delete(self.list_url, data={
            'recorded__gte': self.last_week.isoformat(),
            'recorded__lt': self.now.isoformat(),
            'key': 'foo.bar'})

        eq_(res.status_code, 204)
        eq_(list(MonolithRecord.objects.filter(key='foo.bar')
            .values_list('recorded', flat=True)),
            [self.last_month, self.now])
        eq_(list(MonolithRecord.objects.filter(key='app.install')
            .values_list('recorded', flat=True)),
            [self.last_month, self.now])
