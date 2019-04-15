# -*- coding: utf-8 -*-
from django.conf import settings
from django.core import mail

import mock
import six

from olympia.abuse.models import AbuseReport, GeoIP2Error, GeoIP2Exception
from olympia.amo.tests import TestCase


class TestAbuse(TestCase):
    fixtures = ['base/addon_3615', 'base/user_999']

    def test_choices(self):
        assert AbuseReport.ADDON_SIGNATURES.choices == (
            (None, 'None'),
            (1, 'Curated and partner'),
            (2, 'Curated'),
            (3, 'Partner'),
            (4, 'Non-curated'),
            (5, 'Unsigned'),
        )
        assert AbuseReport.ADDON_SIGNATURES.api_choices == (
            (None, None),
            (1, 'curated_and_partner'),
            (2, 'curated'),
            (3, 'partner'),
            (4, 'non_curated'),
            (5, 'unsigned'),
        )

        assert AbuseReport.REASONS.choices == (
            (None, 'None'),
            (1, 'Malware'),
            (2, 'Spam / Advertising'),
            (3, 'Search / Homepage / New tab page takeover'),
            # '4' No longer exists, but is reserved.
            # (4, 'New tab takeover'),
            (5, 'Breaks websites'),
            (6, 'Offensive'),
            (7, "Doesn't match description"),
            (8, "Doesn't work"),
        )
        assert AbuseReport.REASONS.api_choices == (
            (None, None),
            (1, 'malware'),
            (2, 'spam_or_advertising'),
            (3, 'browser_takeover'),
            # '4' No longer exists, but is reserved.
            # (4, 'new_tab_takeover'),
            (5, 'breaks_websites'),
            (6, 'offensive'),
            (7, 'does_not_match_description'),
            (8, 'does_not_work'),
        )

        assert AbuseReport.ADDON_INSTALL_METHODS.choices == (
            (None, 'None'),
            (1, 'Add-on Manager Web API'),
            (2, 'Direct link'),
            (3, 'Install Trigger'),
            (4, 'From File'),
            (5, 'Webext management API'),
            (6, 'Drag & Drop'),
            (7, 'Sideload'),
        )
        assert AbuseReport.ADDON_INSTALL_METHODS.api_choices == (
            (None, None),
            (1, 'amwebapi'),
            (2, 'link'),
            (3, 'installtrigger'),
            (4, 'install_from_file'),
            (5, 'management_webext_api'),
            (6, 'drag_and_drop'),
            (7, 'sideload'),
        )

        assert AbuseReport.REPORT_ENTRY_POINTS.choices == (
            (None, 'None'),
            (1, 'Uninstall'),
            (2, 'Menu'),
            (3, 'Toolbar context menu'),
        )
        assert AbuseReport.REPORT_ENTRY_POINTS.api_choices == (
            (None, None),
            (1, 'uninstall'),
            (2, 'menu'),
            (3, 'toolbar_context_menu'),
        )

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
