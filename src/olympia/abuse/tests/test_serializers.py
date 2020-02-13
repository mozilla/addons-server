# -*- coding: utf-8 -*-
from datetime import datetime

from unittest.mock import Mock

from django.contrib.auth.models import AnonymousUser
from django.test.client import RequestFactory

from olympia import amo
from olympia.abuse.models import AbuseReport
from olympia.abuse.serializers import (
    AddonAbuseReportSerializer, UserAbuseReportSerializer)
from olympia.accounts.serializers import BaseUserSerializer
from olympia.amo.tests import TestCase, addon_factory, user_factory


class TestAddonAbuseReportSerializer(TestCase):

    def serialize(self, report, **extra_context):
        return AddonAbuseReportSerializer(report, context=extra_context).data

    def test_addon_report(self):
        addon = addon_factory(guid='@guid')
        report = AbuseReport(addon=addon, message='bad stuff')
        serialized = self.serialize(report)
        assert serialized == {
            'reporter': None,
            'addon': {
                'guid': addon.guid,
                'id': addon.id,
                'slug': addon.slug
            },
            'message': 'bad stuff',
            'addon_install_method': None,
            'addon_install_origin': None,
            'addon_install_source': None,
            'addon_install_source_url': None,
            'addon_name': None,
            'addon_signature': None,
            'addon_summary': None,
            'addon_version': None,
            'app': 'firefox',
            'lang': None,
            'appversion': None,
            'client_id': None,
            'install_date': None,
            'operating_system': None,
            'operating_system_version': None,
            'reason': None,
            'report_entry_point': None,
        }

    def test_guid_report(self):
        report = AbuseReport(guid='@guid', message='bad stuff')
        serialized = self.serialize(report)
        assert serialized == {
            'reporter': None,
            'addon': {
                'guid': '@guid',
                'id': None,
                'slug': None
            },
            'message': 'bad stuff',
            'addon_install_method': None,
            'addon_install_origin': None,
            'addon_install_source': None,
            'addon_install_source_url': None,
            'addon_name': None,
            'addon_signature': None,
            'addon_summary': None,
            'addon_version': None,
            'app': 'firefox',
            'lang': None,
            'appversion': None,
            'client_id': None,
            'install_date': None,
            'operating_system': None,
            'operating_system_version': None,
            'reason': None,
            'report_entry_point': None,
        }

    def test_guid_report_to_internal_value_with_some_fancy_parameters(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        view = Mock()
        view.get_guid_and_addon.return_value = {
            'guid': '@someguid',
            'addon': None,
        }
        view.get_addon_object.return_value = None
        extra_context = {
            'request': request,
            'view': view,
        }
        data = {
            'addon': '@someguid',
            'message': u'I am the messagê',
            'addon_install_method': 'url',
            'addon_install_origin': 'http://somewhere.com/',
            'addon_install_source': 'amo',
            'addon_install_source_url': 'https://example.com/sourceme',
            'addon_name': u'Fancy add-on nâme',
            'addon_signature': None,
            'addon_summary': u'A summary',
            'addon_version': '42.42.0',
            'app': 'firefox',
            'lang': 'en-US',
            'appversion': '64.0',
            'client_id': 'somehashedclientid',
            'install_date': '2019-02-25 12:19',
            'operating_system': u'Ôperating System!',
            'operating_system_version': '2019',
            'reason': 'broken',
            'report_entry_point': 'uninstall',
        }
        result = AddonAbuseReportSerializer(
            data, context=extra_context).to_internal_value(data)
        expected = {
            'addon': None,
            'addon_install_method': AbuseReport.ADDON_INSTALL_METHODS.URL,
            'addon_install_origin': 'http://somewhere.com/',
            'addon_install_source': AbuseReport.ADDON_INSTALL_SOURCES.AMO,
            'addon_install_source_url': 'https://example.com/sourceme',
            'addon_name': u'Fancy add-on nâme',
            'addon_signature': None,
            'addon_summary': 'A summary',
            'addon_version': '42.42.0',
            'application': amo.FIREFOX.id,
            'application_locale': 'en-US',
            'application_version': '64.0',
            'client_id': 'somehashedclientid',
            'country_code': '',
            'guid': '@someguid',
            'install_date': datetime(2019, 2, 25, 12, 19),
            'message': u'I am the messagê',
            'operating_system': u'Ôperating System!',
            'operating_system_version': '2019',
            'reason': AbuseReport.REASONS.BROKEN,
            'report_entry_point': AbuseReport.REPORT_ENTRY_POINTS.UNINSTALL,
        }
        assert result == expected


class TestUserAbuseReportSerializer(TestCase):

    def serialize(self, report, **extra_context):
        return UserAbuseReportSerializer(report, context=extra_context).data

    def test_user_report(self):
        user = user_factory()
        report = AbuseReport(user=user, message='bad stuff')
        serialized = self.serialize(report)
        serialized_user = BaseUserSerializer(user).data
        assert serialized == {
            'reporter': None,
            'user': serialized_user,
            'message': 'bad stuff'
        }
