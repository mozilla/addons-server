from collections import namedtuple
import datetime
import json
import uuid

from mock import patch
from nose.tools import eq_

from django.conf import settings
from django.test import client

from amo.tests import TestCase
from mkt.api.tests.test_oauth import BaseOAuth
from mkt.site.fixtures import fixture

from .models import record_stat, MonolithRecord


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


class TestModels(TestCase):

    def setUp(self):
        super(TestModels, self).setUp()
        self.request = RequestFactory()

    def test_record_stat(self):
        now = datetime.datetime.now()
        record_stat('app.install', self.request, recorded=now, value=1)

        # we should have only one record
        record = MonolithRecord.objects.get()

        eq_(record.key, 'app.install')
        eq_(record.value, json.dumps({'value': 1}))
        eq_(record.recorded.timetuple()[0:6], now.timetuple()[0:6])

    def test_record_stat_without_date(self):
        record_stat('app.install', self.request, value=1)
        record = MonolithRecord.objects.get()
        self.assertTrue(record.recorded <= datetime.datetime.now())

    def test_record_stat_without_data(self):
        with self.assertRaises(ValueError):
            record_stat('app.install', self.request)


@patch.object(settings, 'SITE_URL', 'http://api/')
class TestMonolithResource(BaseOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestMonolithResource, self).setUp(api_name='monolith')
        self.grant_permission(self.profile, 'Monolith:API')
        self.list_url = ('api_dispatch_list', {'resource_name': 'data'})
        self.get_url = ('api_dispatch_detail', {'resource_name': 'data'})
        self.now = datetime.datetime(2013, 02, 12, 17, 34)
        self.last_week = self.now - datetime.timedelta(days=7)
        self.yesterday = self.now - datetime.timedelta(days=1)
        self.request = RequestFactory()

    def test_normal_call_with_no_records(self):
        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)

        eq_(data['objects'], [])

    def test_normal_call(self):
        record_stat('app.install', self.request, recorded=self.now, value=2)

        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)

        eq_(len(data['objects']), 1)

        # we also want to test that the data is correct JSON
        eq_(data['objects'][0]['value']['value'], 2)

    def test_filter_by_date(self):
        for id_, date in enumerate((self.last_week, self.yesterday, self.now)):
            record_stat('app.install', self.request, recorded=date, value=id_)

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

    def test_deletion_by_filtering(self):
        # we should be able to delete a set of items using the API
        for id_, date in enumerate((self.last_week, self.yesterday, self.now)):
            record_stat('app.install', self.request, recorded=date, value=id_)

        eq_(MonolithRecord.objects.count(), 3)
        records = MonolithRecord.objects.all()

        res = self.client.delete(self.list_url,
                                 data={'id__gte': records[0].id,
                                       'id__lte': records[1].id})
        eq_(res.status_code, 204)
        eq_(MonolithRecord.objects.count(), 1)

    def test_deletion_by_id(self):
        record_stat('app.install', self.request, recorded=self.now, value=1)
        records = MonolithRecord.objects.all()
        eq_(len(records), 1)

        url = list(self.get_url)
        url[1]['pk'] = records[0].id
        res = self.client.delete(url)

        eq_(res.status_code, 204)
        eq_(MonolithRecord.objects.count(), 0)

    def test_deletion_by_date(self):
        for date in (self.last_week, self.yesterday, self.now):
            record_stat('app.install', self.request, recorded=date, value=1)
            record_stat('foo.bar', self.request, recorded=date, value=1)

        res = self.client.delete(self.list_url, data={
            'recorded__gte': self.last_week.isoformat(),
            'recorded__lte': self.now.isoformat(),
            'key': 'app.install'})

        eq_(res.status_code, 204)
        eq_(MonolithRecord.objects.count(), 3)

        res = self.client.delete(self.list_url, data={
            'recorded__gte': self.last_week.isoformat(),
            'recorded__lte': self.now.isoformat(),
            'key': 'foo.bar'})

        eq_(res.status_code, 204)
        eq_(MonolithRecord.objects.count(), 0)
