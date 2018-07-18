import json

from django.core import mail

from olympia import amo
from olympia.abuse.models import AbuseReport
from olympia.amo.tests import (
    APITestClient,
    TestCase,
    addon_factory,
    reverse_ns,
    user_factory,
)


class AddonAbuseViewSetTestBase(object):
    client_class = APITestClient

    def setUp(self):
        self.url = reverse_ns('abusereportaddon-list')

    def check_reporter(self, report):
        raise NotImplementedError

    def check_report(self, report, text):
        assert unicode(report) == text
        assert report.ip_address == '123.45.67.89'
        assert mail.outbox[0].subject == text
        self.check_reporter(report)

    def test_report_addon_by_id(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': unicode(addon.id), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(addon_id=addon.id).exists()
        report = AbuseReport.objects.get(addon_id=addon.id)
        self.check_report(
            report, u'[Extension] Abuse Report for %s' % addon.name
        )

    def test_report_addon_by_slug(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': addon.slug, 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(addon_id=addon.id).exists()
        report = AbuseReport.objects.get(addon_id=addon.id)
        self.check_report(
            report, u'[Extension] Abuse Report for %s' % addon.name
        )

    def test_report_addon_by_guid(self):
        addon = addon_factory(guid='@badman')
        response = self.client.post(
            self.url,
            data={'addon': addon.guid, 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(addon_id=addon.id).exists()
        report = AbuseReport.objects.get(addon_id=addon.id)
        self.check_report(
            report, u'[Extension] Abuse Report for %s' % addon.name
        )

    def test_report_addon_guid_not_on_amo(self):
        guid = '@mysteryman'
        response = self.client.post(
            self.url,
            data={'addon': guid, 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(guid=guid).exists()
        report = AbuseReport.objects.get(guid=guid)
        self.check_report(report, u'[Addon] Abuse Report for %s' % guid)

    def test_report_addon_invalid_identifier(self):
        response = self.client.post(
            self.url, data={'addon': 'randomnotguid', 'message': 'abuse!'}
        )
        assert response.status_code == 404

    def test_addon_not_public(self):
        addon = addon_factory(status=amo.STATUS_NULL)
        response = self.client.post(
            self.url,
            data={'addon': unicode(addon.id), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(addon_id=addon.id).exists()
        report = AbuseReport.objects.get(addon_id=addon.id)
        self.check_report(
            report, u'[Extension] Abuse Report for %s' % addon.name
        )

    def test_no_addon_fails(self):
        response = self.client.post(self.url, data={'message': 'abuse!'})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Need an addon parameter'
        }

    def test_message_required_empty(self):
        addon = addon_factory()
        response = self.client.post(
            self.url, data={'addon': unicode(addon.id), 'message': ''}
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Abuse reports need a message'
        }

    def test_message_required_missing(self):
        addon = addon_factory()
        response = self.client.post(
            self.url, data={'addon': unicode(addon.id)}
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Abuse reports need a message'
        }

    def test_throttle(self):
        addon = addon_factory()
        for x in xrange(20):
            response = self.client.post(
                self.url,
                data={'addon': unicode(addon.id), 'message': 'abuse!'},
                REMOTE_ADDR='123.45.67.89',
            )
            assert response.status_code == 201, x

        response = self.client.post(
            self.url,
            data={'addon': unicode(addon.id), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 429


class TestAddonAbuseViewSetLoggedOut(AddonAbuseViewSetTestBase, TestCase):
    def check_reporter(self, report):
        assert not report.reporter


class TestAddonAbuseViewSetLoggedIn(AddonAbuseViewSetTestBase, TestCase):
    def setUp(self):
        super(TestAddonAbuseViewSetLoggedIn, self).setUp()
        self.user = user_factory()
        self.client.login_api(self.user)

    def check_reporter(self, report):
        assert report.reporter == self.user


class UserAbuseViewSetTestBase(object):
    client_class = APITestClient

    def setUp(self):
        self.url = reverse_ns('abusereportuser-list')

    def check_reporter(self, report):
        raise NotImplementedError

    def check_report(self, report, text):
        assert unicode(report) == text
        assert report.ip_address == '123.45.67.89'
        assert mail.outbox[0].subject == text
        self.check_reporter(report)

    def test_report_user_id(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={'user': unicode(user.id), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(user_id=user.id).exists()
        report = AbuseReport.objects.get(user_id=user.id)
        self.check_report(report, u'[User] Abuse Report for %s' % user.name)

    def test_report_user_username(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={'user': unicode(user.username), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(user_id=user.id).exists()
        report = AbuseReport.objects.get(user_id=user.id)
        self.check_report(report, u'[User] Abuse Report for %s' % user.name)

    def test_no_user_fails(self):
        response = self.client.post(self.url, data={'message': 'abuse!'})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Need a user parameter'
        }

    def test_message_required_empty(self):
        user = user_factory()
        response = self.client.post(
            self.url, data={'user': unicode(user.username), 'message': ''}
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Abuse reports need a message'
        }

    def test_message_required_missing(self):
        user = user_factory()
        response = self.client.post(
            self.url, data={'user': unicode(user.username)}
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Abuse reports need a message'
        }

    def test_throttle(self):
        user = user_factory()
        for x in xrange(20):
            response = self.client.post(
                self.url,
                data={'user': unicode(user.username), 'message': 'abuse!'},
                REMOTE_ADDR='123.45.67.89',
            )
            assert response.status_code == 201, x

        response = self.client.post(
            self.url,
            data={'user': unicode(user.username), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 429


class TestUserAbuseViewSetLoggedOut(UserAbuseViewSetTestBase, TestCase):
    def check_reporter(self, report):
        assert not report.reporter


class TestUserAbuseViewSetLoggedIn(UserAbuseViewSetTestBase, TestCase):
    def setUp(self):
        super(TestUserAbuseViewSetLoggedIn, self).setUp()
        self.user = user_factory()
        self.client.login_api(self.user)

    def check_reporter(self, report):
        assert report.reporter == self.user
