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
        serial = self.serialize(report)
        assert serial == {'reporter': None,
                          'addon': {'guid': addon.guid,
                                    'id': addon.id,
                                    'slug': addon.slug},
                          'message': 'bad stuff',
                          'addon_install_entry_point': None,
                          'addon_install_method': None,
                          'addon_install_origin': None,
                          'addon_name': None,
                          'addon_signature': None,
                          'addon_summary': None,
                          'addon_version': None,
                          'application': 'firefox',
                          'application_locale': None,
                          'application_version': None,
                          'client_id': None,
                          'install_date': None,
                          'operating_system': None,
                          'operating_system_version': None,
                          'reason': None}

    def test_guid_report(self):
        report = AbuseReport(guid='@guid', message='bad stuff')
        serial = self.serialize(report)
        assert serial == {'reporter': None,
                          'addon': {'guid': '@guid',
                                    'id': None,
                                    'slug': None},
                          'message': 'bad stuff',
                          'addon_install_entry_point': None,
                          'addon_install_method': None,
                          'addon_install_origin': None,
                          'addon_name': None,
                          'addon_signature': None,
                          'addon_summary': None,
                          'addon_version': None,
                          'application': 'firefox',
                          'application_locale': None,
                          'application_version': None,
                          'client_id': None,
                          'install_date': None,
                          'operating_system': None,
                          'operating_system_version': None,
                          'reason': None}


class TestUserAbuseReportSerializer(TestCase):

    def serialize(self, report, **extra_context):
        return UserAbuseReportSerializer(report, context=extra_context).data

    def test_user_report(self):
        user = user_factory()
        report = AbuseReport(user=user, message='bad stuff')
        serial = self.serialize(report)
        user_serial = BaseUserSerializer(user).data
        assert serial == {'reporter': None,
                          'user': user_serial,
                          'message': 'bad stuff'}
