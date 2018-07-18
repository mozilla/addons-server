from olympia.abuse.models import AbuseReport
from olympia.abuse.serializers import (
    AddonAbuseReportSerializer,
    UserAbuseReportSerializer,
)
from olympia.accounts.serializers import BaseUserSerializer
from olympia.amo.tests import BaseTestCase, addon_factory, user_factory


class TestAddonAbuseReportSerializer(BaseTestCase):
    def serialize(self, report, **extra_context):
        return AddonAbuseReportSerializer(report, context=extra_context).data

    def test_addon_report(self):
        addon = addon_factory(guid='@guid')
        report = AbuseReport(addon=addon, message='bad stuff')
        serial = self.serialize(report)
        assert serial == {
            'reporter': None,
            'addon': {'guid': addon.guid, 'id': addon.id, 'slug': addon.slug},
            'message': 'bad stuff',
        }

    def test_guid_report(self):
        report = AbuseReport(guid='@guid', message='bad stuff')
        serial = self.serialize(report)
        assert serial == {
            'reporter': None,
            'addon': {'guid': '@guid', 'id': None, 'slug': None},
            'message': 'bad stuff',
        }


class TestUserAbuseReportSerializer(BaseTestCase):
    def serialize(self, report, **extra_context):
        return UserAbuseReportSerializer(report, context=extra_context).data

    def test_user_report(self):
        user = user_factory()
        report = AbuseReport(user=user, message='bad stuff')
        serial = self.serialize(report)
        user_serial = BaseUserSerializer(user).data
        assert serial == {
            'reporter': None,
            'user': user_serial,
            'message': 'bad stuff',
        }
