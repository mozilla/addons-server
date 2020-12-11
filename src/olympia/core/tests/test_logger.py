# -*- coding: utf-8 -*-
import json
import logging

from unittest import mock

import olympia.core.logger

from olympia.amo.tests import TestCase
from olympia.users.models import UserProfile


class LoggerTests(TestCase):
    def make_fake_record(self, msg='Some fake message', level=logging.NOTSET):
        return logging.LogRecord(
            'loggername',  # name
            level,  # level
            '/some/path',  # pathname
            42,  # lineno
            msg,  # msg
            (),  # args
            None,  # exc_info
        )

    @mock.patch('olympia.core.get_remote_addr', lambda: '127.0.0.1')
    @mock.patch('olympia.core.get_user', lambda: UserProfile(username='fôo'))
    def test_get_logger_adapter(self):
        log = olympia.core.logger.getLogger('test')
        expected_kwargs = {
            'extra': {
                'REMOTE_ADDR': '127.0.0.1',
                'USERNAME': 'fôo',
            }
        }
        assert log.process('test msg', {}) == ('test msg', expected_kwargs)

    @mock.patch('olympia.core.get_remote_addr', lambda: '127.0.0.1')
    @mock.patch('olympia.core.get_user', lambda: None)
    def test_logger_adapter_user_is_none(self):
        log = olympia.core.logger.getLogger('test')
        expected_kwargs = {
            'extra': {
                'REMOTE_ADDR': '127.0.0.1',
                'USERNAME': '<anon>',
            }
        }
        assert log.process('test msg', {}) == ('test msg', expected_kwargs)

    @mock.patch('olympia.core.get_remote_addr', lambda: None)
    @mock.patch('olympia.core.get_user', lambda: UserProfile(username='bar'))
    def test_logger_adapter_addr_is_none(self):
        log = olympia.core.logger.getLogger('test')
        expected_kwargs = {
            'extra': {
                'REMOTE_ADDR': '',
                'USERNAME': 'bar',
            }
        }
        assert log.process('test msg', {}) == ('test msg', expected_kwargs)

    @mock.patch('olympia.core.get_remote_addr', lambda: '127.0.0.1')
    @mock.patch(
        'olympia.core.get_user',
        lambda: UserProfile(username='fôo', email='foo@bar.com'),
    )
    def test_get_logger_adapter_with_extra(self):
        log = olympia.core.logger.getLogger('test')
        expected_kwargs = {
            'extra': {
                'REMOTE_ADDR': '127.0.0.1',
                'USERNAME': 'fôo',
                'email': 'foo@bar.com',
            }
        }
        extra = {'extra': {'email': 'foo@bar.com'}}
        assert log.process('test msg', extra) == ('test msg', expected_kwargs)

    def test_json_formatter(self):
        formatter = olympia.core.logger.JsonFormatter()
        record = self.make_fake_record()
        # These would be set by the adapter.
        record.__dict__['USERNAME'] = 'foo'
        record.__dict__['REMOTE_ADDR'] = '127.0.0.1'
        formatted = json.loads(formatter.format(record))
        assert record.__dict__['uid'] == 'foo'
        assert record.__dict__['remoteAddressChain'] == '127.0.0.1'
        assert formatted['Fields'] == {
            'msg': 'Some fake message',
            'uid': 'foo',
            'remoteAddressChain': '127.0.0.1',
        }

    def test_json_formatter_severity(self):
        formatter = olympia.core.logger.JsonFormatter()

        record = self.make_fake_record(level=logging.NOTSET)
        formatted = json.loads(formatter.format(record))
        assert formatted['severity'] == 0  # For Stackdriver
        assert formatted['Severity'] == 7  # For MozLog 2.0 (7 is default)

        record = self.make_fake_record(level=logging.DEBUG)
        formatted = json.loads(formatter.format(record))
        assert formatted['severity'] == 100  # For Stackdriver
        assert formatted['Severity'] == 7  # For MozLog 2.0

        record = self.make_fake_record(level=logging.INFO)
        formatted = json.loads(formatter.format(record))
        assert formatted['severity'] == 200  # For Stackdriver
        assert formatted['Severity'] == 6  # For MozLog 2.0

        record = self.make_fake_record(level=logging.WARNING)
        formatted = json.loads(formatter.format(record))
        assert formatted['severity'] == 400  # For Stackdriver
        assert formatted['Severity'] == 4  # For MozLog 2.0

        record = self.make_fake_record(level=logging.ERROR)
        formatted = json.loads(formatter.format(record))
        assert formatted['severity'] == 500  # For Stackdriver
        assert formatted['Severity'] == 3  # For MozLog 2.0

        record = self.make_fake_record(level=logging.CRITICAL)
        formatted = json.loads(formatter.format(record))
        assert formatted['severity'] == 600  # For Stackdriver
        assert formatted['Severity'] == 2  # For MozLog 2.0
