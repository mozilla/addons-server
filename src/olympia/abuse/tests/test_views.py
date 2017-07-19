import json

from django.core import mail
from django.core.urlresolvers import reverse

from olympia import amo
from olympia.abuse.models import AbuseReport
from olympia.amo.tests import (
    addon_factory, APITestClient, TestCase, user_factory)


class AbuseReviewSetTestBase(object):
    client_class = APITestClient

    def setUp(self):
        self.url = reverse('abusereport-list')

    def check_reporter(self, report):
        raise NotImplementedError

    def check_report(self, report, text):
        assert unicode(report) == text
        assert report.ip_address
        assert mail.outbox[0].subject == text
        self.check_reporter(report)

    def test_report_addon_by_id(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': unicode(addon.id), 'message': 'abuse!'})
        assert response.status_code == 201

        assert AbuseReport.objects.filter(addon_id=addon.id).exists()
        report = AbuseReport.objects.get(addon_id=addon.id)
        self.check_report(report,
                          u'[Extension] Abuse Report for %s' % addon.name)

    def test_report_addon_by_slug(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': addon.slug, 'message': 'abuse!'})
        assert response.status_code == 201

        assert AbuseReport.objects.filter(addon_id=addon.id).exists()
        report = AbuseReport.objects.get(addon_id=addon.id)
        self.check_report(report,
                          u'[Extension] Abuse Report for %s' % addon.name)

    def test_report_addon_by_guid(self):
        addon = addon_factory(guid='@badman')
        response = self.client.post(
            self.url,
            data={'addon': addon.guid, 'message': 'abuse!'})
        assert response.status_code == 201

        assert AbuseReport.objects.filter(addon_id=addon.id).exists()
        report = AbuseReport.objects.get(addon_id=addon.id)
        self.check_report(report,
                          u'[Extension] Abuse Report for %s' % addon.name)

    def test_report_addon_guid_not_on_amo(self):
        guid = '@mysteryman'
        response = self.client.post(
            self.url,
            data={'addon': guid, 'message': 'abuse!'})
        assert response.status_code == 201

        assert AbuseReport.objects.filter(guid=guid).exists()
        report = AbuseReport.objects.get(guid=guid)
        self.check_report(report,
                          u'[Addon] Abuse Report for %s' % guid)

    def test_report_addon_invalid_identifier(self):
        response = self.client.post(
            self.url,
            data={'addon': 'randomnotguid', 'message': 'abuse!'})
        assert response.status_code == 404

    def test_addon_not_public(self):
        addon = addon_factory(status=amo.STATUS_NULL)
        response = self.client.post(
            self.url,
            data={'addon': unicode(addon.id), 'message': 'abuse!'})
        assert response.status_code == 201

        assert AbuseReport.objects.filter(addon_id=addon.id).exists()
        report = AbuseReport.objects.get(addon_id=addon.id)
        self.check_report(report,
                          u'[Extension] Abuse Report for %s' % addon.name)

    def test_report_user_id(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={'user': unicode(user.id), 'message': 'abuse!'})
        assert response.status_code == 201

        assert AbuseReport.objects.filter(user_id=user.id).exists()
        report = AbuseReport.objects.get(user_id=user.id)
        self.check_report(report,
                          u'[User] Abuse Report for %s' % user.name)

    def test_report_user_username(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={'user': unicode(user.username), 'message': 'abuse!'})
        assert response.status_code == 201

        assert AbuseReport.objects.filter(user_id=user.id).exists()
        report = AbuseReport.objects.get(user_id=user.id)
        self.check_report(report,
                          u'[User] Abuse Report for %s' % user.name)

    def test_both_addon_and_user_fails(self):
        addon = addon_factory()
        user = user_factory()
        response = self.client.post(
            self.url,
            data={'addon': unicode(addon.id),
                  'user': unicode(user.username),
                  'message': 'abuse!'})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Can\'t provide both an addon and user parameter'}

        assert not AbuseReport.objects.filter(addon_id=addon.id).exists()
        assert not AbuseReport.objects.filter(user_id=user.id).exists()

    def test_neither_addon_not_user_fails(self):
        response = self.client.post(
            self.url,
            data={'message': 'abuse!'})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Need an addon or user parameter'}

    def test_message_required(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': unicode(addon.id),
                  'message': ''})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Abuse reports need a message'}

        response = self.client.post(
            self.url,
            data={'addon': unicode(addon.id)})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'detail': 'Abuse reports need a message'}


class TestAbuseReviewSetLoggedOut(AbuseReviewSetTestBase, TestCase):
    def check_reporter(self, report):
        assert not report.reporter


class TestAbuseReviewSetLoggedIn(AbuseReviewSetTestBase, TestCase):
    def setUp(self):
        super(TestAbuseReviewSetLoggedIn, self).setUp()
        self.user = user_factory()
        self.client.login_api(self.user)

    def check_reporter(self, report):
        assert report.reporter == self.user
