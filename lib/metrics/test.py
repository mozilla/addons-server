# -*- coding: utf8 -*-
import json
import urlparse

from django.conf import settings

import mock
from nose.tools import eq_

import amo.tests
from lib.metrics import metrics, send, record_action


@mock.patch('lib.metrics.urllib2.urlopen')
@mock.patch.object(settings, 'METRICS_SERVER', 'http://localhost')
class TestMetrics(amo.tests.TestCase):

    def test_called(self, urlopen):
        send('install', {})
        eq_(urlopen.call_args[0][0].data, '{}')

    def test_called_data(self, urlopen):
        data = {'foo': 'bar'}
        send('install', data)
        eq_(urlopen.call_args[0][0].data, json.dumps(data))

    def test_called_url(self, urlopen):
        send('install', {})
        url = urlopen.call_args[0][0].get_full_url()
        eq_(urlparse.urlparse(url)[:2], ('http', 'localhost'))

    def test_some_unicode(self, urlopen):
        send('install', {'name': u'Вагиф Сәмәдоғлу'})

    @mock.patch('lib.metrics.record_stat')
    def test_record_action(self, record_stat, urlopen):
        request = mock.Mock()
        request.GET = {'src': 'foo'}
        request.LANG = 'en'
        request.META = {'HTTP_USER_AGENT': 'py'}
        record_action('install', request, {})
        assert record_stat.called
        data = json.loads(urlopen.call_args[0][0].data)
        eq_(data['user-agent'], 'py')
        eq_(data['locale'], 'en')
        eq_(data['src'], 'foo')

    def get_response(self, code):
        response = mock.Mock()
        response.getcode.return_value = code
        return response

    def test_error(self, urlopen):
        urlopen.return_value = self.get_response(403)
        eq_(metrics('x', 'install', {}), 403)

    def test_good(self, urlopen):
        urlopen.return_value = self.get_response(201)
        eq_(metrics('x', 'install', {}), 201)

    def test_other(self, urlopen):
        urlopen.return_value = self.get_response(200)
        eq_(metrics('x', 'install', {}), 200)

    def test_uid(self, urlopen):
        metrics('x', 'install', {})
        assert urlopen.call_args[0][0].get_full_url().endswith('x')
