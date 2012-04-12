# -*- coding: utf8 -*-
import urlparse

from django.conf import settings

import mock
from nose.tools import eq_

import amo.tests
from lib.crypto.receipt import sign


@mock.patch('lib.metrics.urllib2.urlopen')
@mock.patch.object(settings, 'SIGNING_SERVER', 'http://localhost')
class TestMetrics(amo.tests.TestCase):

    def test_called(self, urlopen):
        sign('my-receipt')
        eq_(urlopen.call_args[0][0].data, 'my-receipt')

    def test_some_unicode(self, urlopen):
        sign({'name': u'Вагиф Сәмәдоғлу'})

    def get_response(self, code):
        response = mock.Mock()
        response.status_code = code
        return response

    def test_error(self, urlopen):
        urlopen.return_value = self.get_response(403)
        eq_(sign('x'), 403)

    def test_good(self, urlopen):
        urlopen.return_value = self.get_response(200)
        eq_(sign('x'), 200)

    def test_other(self, urlopen):
        urlopen.return_value = self.get_response(206)
        eq_(sign('x'), 206)
