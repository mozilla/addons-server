# -*- coding: utf-8 -*-
from django.conf import settings
from django.core import mail

import mock
import six

from olympia.abuse.models import AbuseReport, GeoIP2Error, GeoIP2Exception
from olympia.amo.tests import TestCase


class TestAbuse(TestCase):
    fixtures = ['base/addon_3615', 'base/user_999']

    def test_user(self):
        report = AbuseReport(user_id=999)
        report.send()
        assert (
            six.text_type(report) ==
            u'[User] Abuse Report for regularuser التطب')
        assert (
            mail.outbox[0].subject ==
            u'[User] Abuse Report for regularuser التطب')
        assert 'user/999' in mail.outbox[0].body

        assert mail.outbox[0].to == [settings.ABUSE_EMAIL]

    def test_addon(self):
        report = AbuseReport(addon_id=3615)
        assert (
            six.text_type(report) ==
            u'[Extension] Abuse Report for Delicious Bookmarks')
        report.send()
        assert (
            mail.outbox[0].subject ==
            u'[Extension] Abuse Report for Delicious Bookmarks')
        assert 'addon/a3615' in mail.outbox[0].body

    def test_addon_fr(self):
        with self.activate(locale='fr'):
            report = AbuseReport(addon_id=3615)
            assert (
                six.text_type(report) ==
                u'[Extension] Abuse Report for Delicious Bookmarks')
            report.send()
        assert (
            mail.outbox[0].subject ==
            u'[Extension] Abuse Report for Delicious Bookmarks')

    def test_guid(self):
        report = AbuseReport(guid='foo@bar.org')
        report.send()
        assert (
            six.text_type(report) ==
            u'[Addon] Abuse Report for foo@bar.org')
        assert (
            mail.outbox[0].subject ==
            u'[Addon] Abuse Report for foo@bar.org')
        assert 'GUID not in database' in mail.outbox[0].body

    @mock.patch('olympia.abuse.models.GeoIP2')
    def test_lookup_country_code_from_ip(self, GeoIP2_mock):
        GeoIP2_mock.return_value.country_code.return_value = 'ZZ'
        assert AbuseReport.lookup_country_code_from_ip('') == ''
        assert AbuseReport.lookup_country_code_from_ip('notanip') == ''
        assert GeoIP2_mock.return_value.country_code.call_count == 0

        GeoIP2_mock.return_value.country_code.return_value = 'ZZ'
        assert AbuseReport.lookup_country_code_from_ip('127.0.0.1') == 'ZZ'
        assert AbuseReport.lookup_country_code_from_ip('::1') == 'ZZ'

        GeoIP2_mock.return_value.country_code.side_effect = GeoIP2Exception
        assert AbuseReport.lookup_country_code_from_ip('127.0.0.1') == ''

        GeoIP2_mock.return_value.country_code.side_effect = GeoIP2Error
        assert AbuseReport.lookup_country_code_from_ip('127.0.0.1') == ''
