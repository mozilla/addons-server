# -*- coding: utf8 -*-
import mock

import amo.tests
from lib.metrics import record_action


class TestMetrics(amo.tests.TestCase):

    @mock.patch('lib.metrics.record_stat')
    def test_record_action(self, record_stat):
        request = mock.Mock()
        request.GET = {'src': 'foo'}
        request.LANG = 'en'
        request.META = {'HTTP_USER_AGENT': 'py'}
        record_action('install', request, {})
        record_stat.assert_called_with('install', request,
            **{'locale': 'en', 'src': 'foo', 'user-agent': 'py'})
