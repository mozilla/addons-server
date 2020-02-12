# -*- coding: utf-8 -*-
import json
from datetime import datetime

from unittest import mock

from olympia import amo
from olympia.abuse.models import AbuseReport
from olympia.amo.tests import (
    APITestClient, TestCase, addon_factory, reverse_ns, user_factory)


class AddonAbuseViewSetTestBase(object):
    client_class = APITestClient

    def setUp(self):
        self.url = reverse_ns('abusereportaddon-list')
        geoip_patcher = mock.patch('olympia.abuse.models.GeoIP2')
        self.GeoIP2_mock = geoip_patcher.start()
        self.GeoIP2_mock.return_value.country_code.return_value = 'ZZ'
        self.addCleanup(geoip_patcher.stop)

    def check_reporter(self, report):
        raise NotImplementedError

    def check_report(self, report, text):
        assert str(report) == text
        assert report.country_code == 'ZZ'
        self.check_reporter(report)

    def test_report_addon_by_id(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': str(addon.id), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89')
        assert response.status_code == 201

        assert AbuseReport.objects.filter(addon_id=addon.id).exists()
        report = AbuseReport.objects.get(addon_id=addon.id)
        assert report.guid == addon.guid
        self.check_report(report,
                          u'[Extension] Abuse Report for %s' % addon.name)
        assert report.message == 'abuse!'

    def test_report_addon_by_slug(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': addon.slug, 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89')
        assert response.status_code == 201

        assert AbuseReport.objects.filter(addon_id=addon.id).exists()
        report = AbuseReport.objects.get(addon_id=addon.id)
        assert report.guid == addon.guid
        self.check_report(report,
                          u'[Extension] Abuse Report for %s' % addon.name)

    def test_report_addon_by_guid(self):
        addon = addon_factory(guid='@badman')
        response = self.client.post(
            self.url,
            data={'addon': addon.guid, 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89')
        assert response.status_code == 201

        assert AbuseReport.objects.filter(addon_id=addon.id).exists()
        report = AbuseReport.objects.get(addon_id=addon.id)
        assert report.guid == addon.guid
        self.check_report(report,
                          u'[Extension] Abuse Report for %s' % addon.name)
        assert report.message == 'abuse!'

    def test_report_addon_guid_not_on_amo(self):
        guid = '@mysteryman'
        response = self.client.post(
            self.url,
            data={'addon': guid, 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89')
        assert response.status_code == 201

        assert AbuseReport.objects.filter(guid=guid).exists()
        report = AbuseReport.objects.get(guid=guid)
        assert not report.addon
        self.check_report(report,
                          u'[Addon] Abuse Report for %s' % guid)
        assert report.message == 'abuse!'

    def test_report_addon_invalid_identifier(self):
        response = self.client.post(
            self.url,
            data={'addon': 'randomnotguid', 'message': 'abuse!'})
        assert response.status_code == 404

    def test_addon_not_public(self):
        addon = addon_factory(status=amo.STATUS_NULL)
        response = self.client.post(
            self.url,
            data={'addon': str(addon.id), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89')
        assert response.status_code == 201

        assert AbuseReport.objects.filter(addon_id=addon.id).exists()
        report = AbuseReport.objects.get(addon_id=addon.id)
        self.check_report(report,
                          u'[Extension] Abuse Report for %s' % addon.name)
        assert report.message == 'abuse!'

    def test_no_addon_fails(self):
        response = self.client.post(
            self.url,
            data={'message': 'abuse!'})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'addon': ['This field is required.']}

    def test_message_required_empty(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': str(addon.id),
                  'message': ''})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'message': ['This field may not be blank.']}

    def test_message_required_missing(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': str(addon.id)})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'message': ['This field is required.']}

    def test_message_not_required_if_reason_is_provided(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': str(addon.id), 'reason': 'broken'},
            REMOTE_ADDR='123.45.67.89')
        assert response.status_code == 201

        assert AbuseReport.objects.filter(addon_id=addon.id).exists()
        report = AbuseReport.objects.get(addon_id=addon.id)
        self.check_report(report,
                          u'[Extension] Abuse Report for %s' % addon.name)
        assert report.message == ''

    def test_message_can_be_blank_if_reason_is_provided(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': str(addon.id), 'reason': 'broken',
                  'message': ''},
            REMOTE_ADDR='123.45.67.89')
        assert response.status_code == 201

        assert AbuseReport.objects.filter(addon_id=addon.id).exists()
        report = AbuseReport.objects.get(addon_id=addon.id)
        self.check_report(report,
                          u'[Extension] Abuse Report for %s' % addon.name)
        assert report.message == ''

    def test_message_length_limited(self):
        addon = addon_factory()

        response = self.client.post(
            self.url,
            data={'addon': str(addon.id),
                  'message': 'a' * 10000})
        assert response.status_code == 201

        response = self.client.post(
            self.url,
            data={'addon': str(addon.id),
                  'message': 'a' * 10001})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'message': [
                'Please ensure this field has no more than 10000 characters.'
            ]
        }

    def test_throttle(self):
        addon = addon_factory()
        for x in range(20):
            response = self.client.post(
                self.url,
                data={'addon': str(addon.id), 'message': 'abuse!'},
                REMOTE_ADDR='123.45.67.89')
            assert response.status_code == 201, x

        response = self.client.post(
            self.url,
            data={'addon': str(addon.id), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89')
        assert response.status_code == 429

    def test_optional_fields(self):
        data = {
            'addon': '@mysteryaddon',
            'message': u'This is abusé!',
            'client_id': 'i' * 64,
            'addon_name': u'Addon Næme',
            'addon_summary': u'Addon sûmmary',
            'addon_version': '0.01.01',
            'addon_signature': None,
            'app': 'firefox',
            'appversion': '42.0.1',
            'lang': u'Lô-käl',
            'operating_system': u'Sømething OS',
            'install_date': '2004-08-15T16:23:42',
            'reason': 'spam',
            'addon_install_origin': 'http://example.com/',
            'addon_install_method': 'url',
            'report_entry_point': None,
        }
        response = self.client.post(
            self.url,
            data=data,
            REMOTE_ADDR='123.45.67.89')
        assert response.status_code == 201, response.content

        assert AbuseReport.objects.filter(guid=data['addon']).exists()
        report = AbuseReport.objects.get(guid=data['addon'])
        self.check_report(
            report, u'[Addon] Abuse Report for %s' % data['addon'])
        assert not report.addon  # Not an add-on in database, that's ok.
        # Straightforward comparisons:
        for field in ('message', 'client_id', 'addon_name', 'addon_summary',
                      'addon_version', 'operating_system',
                      'addon_install_origin'):
            assert getattr(report, field) == data[field], field
        # More complex comparisons:
        assert report.addon_signature is None
        assert report.application == amo.FIREFOX.id
        assert report.application_version == data['appversion']
        assert report.application_locale == data['lang']
        assert report.install_date == datetime(2004, 8, 15, 16, 23, 42)
        assert report.reason == 2  # Spam / Advertising
        assert report.addon_install_method == (
            AbuseReport.ADDON_INSTALL_METHODS.URL)
        assert report.addon_install_source is None
        assert report.addon_install_source_url is None
        assert report.report_entry_point is None

    def test_optional_fields_errors(self):
        data = {
            'addon': '@mysteryaddon',
            'message': u'Message cân be quite big if needed' * 256,
            'client_id': 'i' * 65,
            'addon_name': 'a' * 256,
            'addon_summary': 's' * 256,
            'addon_version': 'v' * 256,
            'addon_signature': 'Something not in signature choices',
            'app': 'FIRE! EXCLAMATION MARK',
            'appversion': '1' * 256,
            'lang': 'l' * 256,
            'operating_system': 'o' * 256,
            'install_date': 'not_a_date',
            'reason': 'Something not in reason choices',
            'addon_install_origin': 'u' * 256,
            'addon_install_method': 'Something not in install method choices',
            'addon_install_source': 'Something not in install source choices',
            'addon_install_source_url': 'http://%s' % 'a' * 249,
            'report_entry_point': 'Something not in entrypoint choices',
        }
        response = self.client.post(
            self.url,
            data=data,
            REMOTE_ADDR='123.45.67.89')
        assert response.status_code == 400
        expected_max_length_message = (
            'Ensure this field has no more than %d characters.')
        expected_choices_message = '"%s" is not a valid choice.'
        assert response.json() == {
            'client_id': [expected_max_length_message % 64],
            'addon_name': [expected_max_length_message % 255],
            'addon_summary': [expected_max_length_message % 255],
            'addon_version': [expected_max_length_message % 255],
            'addon_signature': [
                expected_choices_message % data['addon_signature']],
            'app': [expected_choices_message % data['app']],
            'appversion': [expected_max_length_message % 255],
            'lang': [expected_max_length_message % 255],
            'operating_system': [expected_max_length_message % 255],
            'install_date': [
                'Datetime has wrong format. Use one of these formats '
                'instead: YYYY-MM-DDThh:mm[:ss[.uuuuuu]][+HH:MM|-HH:MM|Z].'],
            'reason': [expected_choices_message % data['reason']],
            'addon_install_origin': [expected_max_length_message % 255],
            'addon_install_source_url': [expected_max_length_message % 255],
            'report_entry_point': [
                expected_choices_message % data['report_entry_point']],
        }
        # Note: addon_install_method and addon_install_source silently convert
        # unknown values to "other", so the values submitted here, despite not
        # being valid choices, aren't considered errors. See
        # test_addon_unknown_install_source_and_method() below.

    def test_addon_unknown_install_source_and_method(self):
        data = {
            'addon': '@mysteryaddon',
            'message': 'This is abusé!',
            'addon_install_method': 'something unexpected' * 15,
            'addon_install_source': 'something unexpected indeed',
        }
        response = self.client.post(self.url, data=data)
        assert response.status_code == 201, response.content

        assert AbuseReport.objects.filter(guid=data['addon']).exists()
        report = AbuseReport.objects.get(guid=data['addon'])
        self.check_report(
            report, u'[Addon] Abuse Report for %s' % data['addon'])
        assert not report.addon  # Not an add-on in database, that's ok.
        assert report.addon_install_method == (
            AbuseReport.ADDON_INSTALL_METHODS.OTHER)
        assert report.addon_install_source == (
            AbuseReport.ADDON_INSTALL_SOURCES.OTHER)

    def test_addon_unknown_install_source_and_method_not_string(self):
        addon = addon_factory()
        data = {
            'addon': str(addon.pk),
            'message': 'This is abusé!',
            'addon_install_method': 42,
            'addon_install_source': 53,
        }
        response = self.client.post(self.url, data=data)
        assert response.status_code == 201, response.content

        assert AbuseReport.objects.filter(guid=addon.guid).exists()
        report = AbuseReport.objects.get(addon=addon)
        self.check_report(
            report, u'[Extension] Abuse Report for %s' % addon.name)
        assert report.addon == addon
        assert report.addon_install_method == (
            AbuseReport.ADDON_INSTALL_METHODS.OTHER)
        assert report.addon_install_source == (
            AbuseReport.ADDON_INSTALL_SOURCES.OTHER)


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
        geoip_patcher = mock.patch('olympia.abuse.models.GeoIP2')
        self.GeoIP2_mock = geoip_patcher.start()
        self.GeoIP2_mock.return_value.country_code.return_value = 'ZZ'
        self.addCleanup(geoip_patcher.stop)

    def check_reporter(self, report):
        raise NotImplementedError

    def check_report(self, report, text):
        assert str(report) == text
        assert report.country_code == 'ZZ'
        self.check_reporter(report)

    def test_report_user_id(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={'user': str(user.id), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89')
        assert response.status_code == 201

        assert AbuseReport.objects.filter(user_id=user.id).exists()
        report = AbuseReport.objects.get(user_id=user.id)
        self.check_report(report,
                          u'[User] Abuse Report for %s' % user.name)

    def test_report_user_username(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={'user': str(user.username), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89')
        assert response.status_code == 201

        assert AbuseReport.objects.filter(user_id=user.id).exists()
        report = AbuseReport.objects.get(user_id=user.id)
        self.check_report(report,
                          u'[User] Abuse Report for %s' % user.name)

    def test_no_user_fails(self):
        response = self.client.post(
            self.url,
            data={'message': 'abuse!'})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'user': ['This field is required.']}

    def test_message_required_empty(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={'user': str(user.username), 'message': ''})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'message': ['This field may not be blank.']}

    def test_message_required_missing(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={'user': str(user.username)})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'message': ['This field is required.']}

    def test_throttle(self):
        user = user_factory()
        for x in range(20):
            response = self.client.post(
                self.url,
                data={'user': str(
                    user.username), 'message': 'abuse!'},
                REMOTE_ADDR='123.45.67.89')
            assert response.status_code == 201, x

        response = self.client.post(
            self.url,
            data={'user': str(user.username), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89')
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
