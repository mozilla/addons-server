from olympia.abuse.models import AbuseReport
from olympia.abuse.serializers import AbuseReportSerializer
from olympia.amo.tests import (
    addon_factory, BaseTestCase, user_factory)
from olympia.users.serializers import BaseUserSerializer


class TestAbuseReportSerializer(BaseTestCase):

    def serialize(self, report, **extra_context):
        return AbuseReportSerializer(report, context=extra_context).data

    def test_addon_report(self):
        addon = addon_factory(guid='@guid')
        report = AbuseReport(addon=addon, message='bad stuff')
        serial = self.serialize(report)
        assert serial == {'reporter': None,
                          'ip_address': '0.0.0.0',
                          'addon': {'guid': addon.guid,
                                    'id': addon.id,
                                    'slug': addon.slug},
                          'user': None,
                          'message': 'bad stuff'}

    def test_guid_report(self):
        report = AbuseReport(guid='@guid', message='bad stuff')
        serial = self.serialize(report)
        assert serial == {'reporter': None,
                          'ip_address': '0.0.0.0',
                          'addon': {'guid': '@guid',
                                    'id': None,
                                    'slug': None},
                          'user': None,
                          'message': 'bad stuff'}

    def test_user_report(self):
        user = user_factory()
        report = AbuseReport(user=user, message='bad stuff')
        serial = self.serialize(report)
        user_serial = BaseUserSerializer(user).data
        assert serial == {'reporter': None,
                          'ip_address': '0.0.0.0',
                          'addon': None,
                          'user': user_serial,
                          'message': 'bad stuff'}
