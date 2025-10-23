import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.core import mail
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes

import time_machine
from pyquery import PyQuery as pq
from rest_framework.test import APIRequestFactory
from waffle.testutils import override_switch

from olympia import amo
from olympia.abuse.forms import AbuseAppealEmailForm, AbuseAppealForm
from olympia.addons.models import AddonRegionalRestrictions
from olympia.amo.tests import (
    APITestClientSessionID,
    TestCase,
    addon_factory,
    collection_factory,
    get_random_ip,
    reverse_ns,
    user_factory,
)
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.core import get_user, set_user
from olympia.ratings.models import Rating

from ..actions import (
    ContentActionApproveNoAction,
    ContentActionDisableAddon,
    ContentActionTargetAppealApprove,
    ContentActionTargetAppealRemovalAffirmation,
)
from ..models import AbuseReport, CinderAppeal, CinderJob, ContentDecision
from ..views import CinderInboundPermission, cinder_webhook, filter_enforcement_actions


TESTS_DIR = os.path.dirname(os.path.abspath(__file__))


class AddonAbuseViewSetTestBase:
    client_class = APITestClientSessionID

    def setUp(self):
        self.url = reverse_ns('abusereportaddon-list')

    def check_reporter(self, report):
        raise NotImplementedError

    def check_report(self, report, text):
        assert str(report) == text
        self.check_reporter(report)

    def test_report_addon_by_id(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': str(addon.id), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201

        # It was a public add-on, so we found its guid.
        assert AbuseReport.objects.filter(guid=addon.guid).exists()
        report = AbuseReport.objects.get(guid=addon.guid)
        self.check_report(report, f'Abuse Report for Addon {addon.guid}')
        assert report.message == 'abuse!'

    def test_report_addon_by_id_int(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': addon.pk, 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201

        # It was a public add-on, so we found its guid.
        assert AbuseReport.objects.filter(guid=addon.guid).exists()
        report = AbuseReport.objects.get(guid=addon.guid)
        self.check_report(report, f'Abuse Report for Addon {addon.guid}')
        assert report.message == 'abuse!'

    def test_report_addon_by_slug(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': addon.slug, 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201

        # It was a public add-on, so we found its guid.
        assert AbuseReport.objects.filter(guid=addon.guid).exists()
        report = AbuseReport.objects.get(guid=addon.guid)
        self.check_report(report, f'Abuse Report for Addon {addon.guid}')

    def test_report_addon_by_guid(self):
        addon = addon_factory(guid='@badman')
        response = self.client.post(
            self.url,
            data={'addon': addon.guid, 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(guid=addon.guid).exists()
        report = AbuseReport.objects.get(guid=addon.guid)
        self.check_report(report, f'Abuse Report for Addon {addon.guid}')
        assert report.message == 'abuse!'

    def test_report_addon_by_id_not_public(self):
        addon = addon_factory(status=amo.STATUS_DISABLED)
        response = self.client.post(
            self.url,
            data={'addon': addon.pk, 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 404

    def test_report_addon_by_slug_not_public(self):
        addon = addon_factory(status=amo.STATUS_DISABLED)
        response = self.client.post(
            self.url,
            data={'addon': addon.slug, 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 404

    def test_report_addon_by_guid_not_public(self):
        addon = addon_factory(guid='@badman', status=amo.STATUS_DISABLED)
        response = self.client.post(
            self.url,
            data={'addon': addon.guid, 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201

        # We accept any report by guid, even if the add-on is not public or
        # simply inexistant (see test below) since we're not linking them
        assert AbuseReport.objects.filter(guid=addon.guid).exists()
        report = AbuseReport.objects.get(guid=addon.guid)
        self.check_report(report, f'Abuse Report for Addon {addon.guid}')
        assert report.message == 'abuse!'

    def test_report_addon_guid_not_on_amo(self):
        guid = '@mysteryman'
        response = self.client.post(
            self.url,
            data={'addon': guid, 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(guid=guid).exists()
        report = AbuseReport.objects.get(guid=guid)
        self.check_report(report, 'Abuse Report for Addon %s' % guid)
        assert report.message == 'abuse!'

    def test_report_addon_invalid_identifier(self):
        response = self.client.post(
            self.url, data={'addon': 'randomnotguid', 'message': 'abuse!'}
        )
        assert response.status_code == 404

    def test_addon_not_public(self):
        addon = addon_factory(status=amo.STATUS_NULL)
        response = self.client.post(
            self.url,
            data={'addon': str(addon.id), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        # Fails: for non public add-ons, you have to use the guid.
        assert response.status_code == 404

    def test_addon_not_public_by_guid(self):
        addon = addon_factory(status=amo.STATUS_NULL)
        response = self.client.post(
            self.url,
            data={'addon': str(addon.guid), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(guid=addon.guid).exists()
        report = AbuseReport.objects.get(guid=addon.guid)
        self.check_report(report, f'Abuse Report for Addon {addon.guid}')
        assert report.message == 'abuse!'

    def test_addon_georestricted(self):
        addon = addon_factory()
        AddonRegionalRestrictions.objects.create(addon=addon, excluded_regions=['FR'])
        response = self.client.post(
            self.url,
            data={'addon': str(addon.guid), 'message': 'geo abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
            HTTP_X_COUNTRY_CODE='FR',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(guid=addon.guid).exists()
        report = AbuseReport.objects.get(guid=addon.guid)
        self.check_report(report, f'Abuse Report for Addon {addon.guid}')
        assert report.message == 'geo abuse!'

    def test_no_addon_fails(self):
        response = self.client.post(self.url, data={'message': 'abuse!'})
        assert response.status_code == 400
        assert json.loads(response.content) == {'addon': ['This field is required.']}

    def test_reason_all_reasons_available(self):
        addon = addon_factory()
        reason = AbuseReport.REASONS.DOES_NOT_WORK

        # Reason is not in the CONTENT_REASONS subset, but should still be
        # accepted.
        assert reason not in AbuseReport.REASONS.CONTENT_REASONS
        response = self.client.post(
            self.url,
            data={
                'addon': str(addon.guid),
                'message': 'foo',
                'reason': reason.constant.lower(),
            },
        )
        assert response.status_code == 201
        report = AbuseReport.objects.get(guid=addon.guid)
        assert report.reason == reason.value

    def test_message_required_empty(self):
        addon = addon_factory()
        response = self.client.post(
            self.url, data={'addon': str(addon.id), 'message': ''}
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'message': ['This field may not be blank.']
        }

    def test_message_required_missing(self):
        addon = addon_factory()
        response = self.client.post(self.url, data={'addon': str(addon.id)})
        assert response.status_code == 400
        assert json.loads(response.content) == {'message': ['This field is required.']}

    def test_message_not_required_if_reason_is_provided(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': str(addon.id), 'reason': 'broken'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(guid=addon.guid).exists()
        report = AbuseReport.objects.get(guid=addon.guid)
        self.check_report(report, f'Abuse Report for Addon {addon.guid}')
        assert report.message == ''

    def test_message_can_be_blank_if_reason_is_provided(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={'addon': str(addon.id), 'reason': 'broken', 'message': ''},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(guid=addon.guid).exists()
        report = AbuseReport.objects.get(guid=addon.guid)
        self.check_report(report, f'Abuse Report for Addon {addon.guid}')
        assert report.message == ''

    def test_message_length_limited(self):
        addon = addon_factory()

        response = self.client.post(
            self.url, data={'addon': str(addon.id), 'message': 'a' * 10000}
        )
        assert response.status_code == 201

        response = self.client.post(
            self.url, data={'addon': str(addon.id), 'message': 'a' * 10001}
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'message': ['Please ensure this field has no more than 10000 characters.']
        }

    def test_throttle(self):
        addon = addon_factory()
        for x in range(20):
            response = self.client.post(
                self.url,
                data={'addon': str(addon.id), 'message': 'abuse!'},
                REMOTE_ADDR='123.45.67.89',
                HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
            )
            assert response.status_code == 201, x

        response = self.client.post(
            self.url,
            data={'addon': str(addon.id), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 429

    def test_optional_fields(self):
        data = {
            'addon': '@mysteryaddon',
            'message': 'This is abusé!',
            'client_id': 'i' * 64,
            'addon_name': 'Addon Næme',
            'addon_summary': 'Addon sûmmary',
            'addon_version': '0.01.01',
            'addon_signature': None,
            'app': 'firefox',
            'appversion': '42.0.1',
            'lang': 'Lô-käl',
            'operating_system': 'Sømething OS',
            'install_date': '2004-08-15T16:23:42',
            'reason': 'spam',
            'addon_install_origin': 'http://example.com/',
            'addon_install_method': 'url',
            'report_entry_point': None,
            'reporter_name': 'Somebody',
            'reporter_email': 'some@body.com',
            'location': 'addon',
        }
        response = self.client.post(
            self.url,
            data=data,
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201, response.content

        assert AbuseReport.objects.filter(guid=data['addon']).exists()
        report = AbuseReport.objects.get(guid=data['addon'])
        self.check_report(report, 'Abuse Report for Addon %s' % data['addon'])
        # Straightforward comparisons:
        for field in (
            'message',
            'client_id',
            'addon_name',
            'addon_summary',
            'addon_version',
            'operating_system',
            'addon_install_origin',
            'reporter_name',
            'reporter_email',
        ):
            assert getattr(report, field) == data[field], field
        # More complex comparisons:
        assert report.addon_signature is None
        assert report.application == amo.FIREFOX.id
        assert report.application_version == data['appversion']
        assert report.application_locale == data['lang']
        assert report.install_date == datetime(2004, 8, 15, 16, 23, 42)
        assert report.reason == 2  # Spam / Advertising
        assert report.addon_install_method == (AbuseReport.ADDON_INSTALL_METHODS.URL)
        assert report.addon_install_source is None
        assert report.addon_install_source_url is None
        assert report.report_entry_point is None
        assert report.location == 2

    def test_reporter_name_email_reason_fields_can_be_null(self):
        data = {
            'addon': '@mysteryaddon',
            'message': 'This is abusé!',
            'reason': None,
            'reporter_name': None,
            'reporter_email': None,
        }
        response = self.client.post(
            self.url,
            data=data,
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201, response.content

        assert AbuseReport.objects.filter(guid=data['addon']).exists()
        report = AbuseReport.objects.get(guid=data['addon'])
        self.check_report(report, 'Abuse Report for Addon %s' % data['addon'])
        # Straightforward comparisons:
        for field in (
            'reason',
            'reporter_name',
            'reporter_email',
        ):
            assert getattr(report, field) is None

    def test_optional_fields_errors(self):
        data = {
            'addon': '@mysteryaddon',
            'message': 'Message cân be quite big if needed' * 256,
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
            'reporter_name': 'n' * 256,
            'reporter_email': 'not an email address',
            'location': 'A location not in location choices',
        }
        response = self.client.post(
            self.url,
            data=data,
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 400
        expected_max_length_message = (
            'Ensure this field has no more than %d characters.'
        )
        expected_choices_message = '"%s" is not a valid choice.'
        assert response.json() == {
            'client_id': [expected_max_length_message % 64],
            'addon_name': [expected_max_length_message % 255],
            'addon_summary': [expected_max_length_message % 255],
            'addon_version': [expected_max_length_message % 255],
            'addon_signature': [expected_choices_message % data['addon_signature']],
            'app': [expected_choices_message % data['app']],
            'appversion': [expected_max_length_message % 255],
            'lang': [expected_max_length_message % 255],
            'operating_system': [expected_max_length_message % 255],
            'install_date': [
                'Datetime has wrong format. Use one of these formats '
                'instead: YYYY-MM-DDThh:mm[:ss[.uuuuuu]][+HH:MM|-HH:MM|Z].'
            ],
            'reason': [expected_choices_message % data['reason']],
            'addon_install_origin': [expected_max_length_message % 255],
            'addon_install_source_url': [expected_max_length_message % 255],
            'report_entry_point': [
                expected_choices_message % data['report_entry_point']
            ],
            'reporter_name': [expected_max_length_message % 255],
            'reporter_email': ['Enter a valid email address.'],
            'location': [expected_choices_message % data['location']],
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
        self.check_report(report, 'Abuse Report for Addon %s' % data['addon'])
        assert report.addon_install_method == (AbuseReport.ADDON_INSTALL_METHODS.OTHER)
        assert report.addon_install_source == (AbuseReport.ADDON_INSTALL_SOURCES.OTHER)

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
        report = AbuseReport.objects.get(guid=addon.guid)
        self.check_report(report, f'Abuse Report for Addon {addon.guid}')
        assert report.addon_install_method == (AbuseReport.ADDON_INSTALL_METHODS.OTHER)
        assert report.addon_install_source == (AbuseReport.ADDON_INSTALL_SOURCES.OTHER)

    def test_report_country_code(self):
        addon = addon_factory(status=amo.STATUS_NULL)
        response = self.client.post(
            self.url,
            data={'addon': str(addon.guid), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
            HTTP_X_COUNTRY_CODE='YY',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(guid=addon.guid).exists()
        report = AbuseReport.objects.get(guid=addon.guid)
        self.check_report(report, f'Abuse Report for Addon {addon.guid}')
        assert report.country_code == 'YY'

    def test_abuse_report_with_invalid_data(self):
        addon = addon_factory()
        # Prepare data with invalid field values
        data = {
            'addon': addon.pk,
            'addon_install_method': {'dictionary_key': 'dictionary_val'},
            'addon_install_source': {'dictionary_key': 'dictionary_val'},
            'message': 'abuse!',
        }

        response = self.client.post(self.url, data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {'addon_install_method': 'Invalid value'}

    def _setup_reportable_reason(self, reason, *, addon=None, extra_data=None):
        addon = addon or addon_factory(guid='@badman')
        response = self.client.post(
            self.url,
            data={'addon': addon.guid, 'reason': reason, **(extra_data or {})},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201, response.content

    @mock.patch('olympia.abuse.tasks.report_to_cinder.delay')
    @override_switch('dsa-job-technical-processing', active=True)
    def test_reportable_reason_calls_cinder_task(self, task_mock):
        self._setup_reportable_reason('hateful_violent_deceptive')
        task_mock.assert_called()

    @mock.patch('olympia.abuse.tasks.report_to_cinder.delay')
    @override_switch('dsa-job-technical-processing', active=True)
    def test_reportable_reason_does_call_if_version_listed(self, task_mock):
        addon = addon_factory(guid='@badman')
        self._setup_reportable_reason(
            'hateful_violent_deceptive',
            addon=addon,
            extra_data={'addon_version': addon.current_version.version},
        )
        task_mock.assert_called()

    @mock.patch('olympia.abuse.tasks.report_to_cinder.delay')
    @override_switch('dsa-job-technical-processing', active=True)
    def test_reportable_reason_does_not_call_if_version_unlisted(self, task_mock):
        addon = addon_factory(guid='@badman')
        version = addon.current_version
        self.make_addon_unlisted(addon)
        self._setup_reportable_reason(
            'hateful_violent_deceptive',
            addon=addon,
            extra_data={'addon_version': version.version},
        )
        task_mock.assert_not_called()

    @mock.patch('olympia.abuse.tasks.report_to_cinder.delay')
    @override_switch('dsa-job-technical-processing', active=False)
    def test_reportable_reason_does_not_call_cinder_with_waffle_off(self, task_mock):
        self._setup_reportable_reason('hateful_violent_deceptive')
        task_mock.assert_not_called()

    @mock.patch('olympia.abuse.tasks.report_to_cinder.delay')
    @override_switch('dsa-job-technical-processing', active=True)
    def test_not_reportable_reason_does_not_call_cinder_task(self, task_mock):
        self._setup_reportable_reason('feedback_spam')
        task_mock.assert_not_called()

    def test_reject_illegal_category_when_reason_is_not_illegal(self):
        addon = addon_factory(guid='@badman')
        response = self.client.post(
            self.url,
            data={
                'addon': addon.guid,
                'reason': 'feedback_spam',
                'illegal_category': 'other',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': [
                'This value must be omitted or set to "null" when the `reason` is '
                'not "illegal".'
            ],
        }

    def test_reject_illegal_subcategory_when_reason_is_not_illegal(self):
        addon = addon_factory(guid='@badman')
        response = self.client.post(
            self.url,
            data={
                'addon': addon.guid,
                'reason': 'feedback_spam',
                'illegal_subcategory': 'other',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': [
                'This value must be omitted or set to "null" when the `reason` is '
                'not "illegal".'
            ],
        }

    def test_illegal_category_required_when_reason_is_illegal(self):
        addon = addon_factory(guid='@badman')
        response = self.client.post(
            self.url, data={'addon': addon.guid, 'reason': 'illegal'}
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': ['This field is required.']
        }

    def test_illegal_category_cannot_be_blank_when_reason_is_illegal(self):
        addon = addon_factory(guid='@badman')
        response = self.client.post(
            self.url,
            data={
                'addon': addon.guid,
                'reason': 'illegal',
                'illegal_category': '',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': ['"" is not a valid choice.']
        }

    def test_illegal_category_cannot_be_null_when_reason_is_illegal(self):
        addon = addon_factory(guid='@badman')
        response = self.client.post(
            self.url,
            data={
                'addon': addon.guid,
                'reason': 'illegal',
                'illegal_category': None,
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': ['This field may not be null.']
        }

    def test_illegal_subcategory_required_when_reason_is_illegal(self):
        addon = addon_factory(guid='@badman')
        response = self.client.post(
            self.url,
            data={
                'addon': addon.guid,
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': ['This field is required.']
        }

    def test_illegal_subcategory_cannot_be_blank_when_reason_is_illegal(self):
        addon = addon_factory(guid='@badman')
        response = self.client.post(
            self.url,
            data={
                'addon': addon.guid,
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': '',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': ['"" is not a valid choice.']
        }

    def test_illegal_subcategory_cannot_be_null_when_reason_is_illegal(self):
        addon = addon_factory(guid='@badman')
        response = self.client.post(
            self.url,
            data={
                'addon': addon.guid,
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': None,
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': ['This field may not be null.']
        }

    def test_illegal_subcategory_depends_on_category(self):
        addon = addon_factory(guid='@badman')
        response = self.client.post(
            self.url,
            data={
                'addon': addon.guid,
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'biometric_data_breach',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': [
                'This value cannot be used in combination with the supplied '
                '`illegal_category`.'
            ]
        }

    def test_addon_signature_unknown(self):
        addon = addon_factory()
        response = self.client.post(
            self.url,
            data={
                'addon': str(addon.id),
                'message': 'abuse!',
                'addon_signature': 'unknown: undefined',
            },
        )
        assert response.status_code == 201

        report = AbuseReport.objects.get(guid=addon.guid)
        assert report.addon_signature == AbuseReport.ADDON_SIGNATURES.UNKNOWN


class TestAddonAbuseViewSetLoggedOut(AddonAbuseViewSetTestBase, TestCase):
    def check_reporter(self, report):
        assert not report.reporter


class TestAddonAbuseViewSetLoggedIn(AddonAbuseViewSetTestBase, TestCase):
    def setUp(self):
        super().setUp()
        self.user = user_factory()
        self.client.login_api(self.user)

    def check_reporter(self, report):
        assert report.reporter == self.user

    def test_throttle_ip_for_authenticated_users(self):
        user = user_factory()
        self.client.login_api(user)
        addon = addon_factory()
        for x in range(20):
            response = self.client.post(
                self.url,
                data={'addon': str(addon.id), 'message': 'abuse!'},
                REMOTE_ADDR='123.45.67.89',
                HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
            )
            assert response.status_code == 201, x

        # Different user, same IP: should still be blocked (> 20 / day).
        new_user = user_factory()
        self.client.login_api(new_user)
        response = self.client.post(
            self.url,
            data={'addon': str(addon.id), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 429


class UserAbuseViewSetTestBase:
    client_class = APITestClientSessionID

    def setUp(self):
        self.url = reverse_ns('abusereportuser-list')

    def check_reporter(self, report):
        raise NotImplementedError

    def check_report(self, report, text):
        assert str(report) == text
        self.check_reporter(report)

    def test_report_user_id(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={'user': str(user.id), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(user_id=user.id).exists()
        report = AbuseReport.objects.get(user_id=user.id)
        self.check_report(report, f'Abuse Report for User {user.pk}')

    def test_report_user_id_int(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={'user': user.pk, 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(user_id=user.pk).exists()
        report = AbuseReport.objects.get(user_id=user.pk)
        self.check_report(report, f'Abuse Report for User {user.pk}')

    def test_report_user_username(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={'user': str(user.username), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(user_id=user.id).exists()
        report = AbuseReport.objects.get(user_id=user.id)
        self.check_report(report, f'Abuse Report for User {user.pk}')

    def test_no_user_fails(self):
        response = self.client.post(self.url, data={'message': 'abuse!'})
        assert response.status_code == 400
        assert json.loads(response.content) == {'user': ['This field is required.']}

    def test_message_required_empty(self):
        user = user_factory()
        response = self.client.post(
            self.url, data={'user': str(user.username), 'message': ''}
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'message': ['This field may not be blank.']
        }

    def test_message_required_missing(self):
        user = user_factory()
        response = self.client.post(self.url, data={'user': str(user.username)})
        assert response.status_code == 400
        assert json.loads(response.content) == {'message': ['This field is required.']}

    def test_message_not_required_with_content_reason(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={
                'user': str(user.username),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
        )
        assert response.status_code == 201

    def test_non_content_reason_not_accepted(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={
                'user': str(user.username),
                'reason': 'policy_violation',
                'message': 'some message',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'reason': ['"policy_violation" is not a valid choice.']
        }

        response = self.client.post(
            self.url,
            data={
                'user': str(user.username),
                'reason': 'illegal',
                'message': 'Fine!',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
        )
        assert response.status_code == 201

    def test_throttle(self):
        user = user_factory()
        for x in range(20):
            response = self.client.post(
                self.url,
                data={'user': str(user.username), 'message': 'abuse!'},
                REMOTE_ADDR='123.45.67.89',
                HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
            )
            assert response.status_code == 201, x

        response = self.client.post(
            self.url,
            data={'user': str(user.username), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 429

    def test_report_country_code(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={'user': str(user.id), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_COUNTRY_CODE='YY',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(user_id=user.id).exists()
        report = AbuseReport.objects.get(user_id=user.id)
        self.check_report(report, f'Abuse Report for User {user.pk}')
        assert report.country_code == 'YY'

    def _setup_reportable_reason(self, reason, message=None):
        user = user_factory(display_name='baduser')
        data = {'user': user.pk}
        if message is not None:
            data['message'] = message
        if reason is not None:
            data['reason'] = reason
        response = self.client.post(
            self.url,
            data=data,
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201, response.content

    @mock.patch('olympia.abuse.tasks.report_to_cinder.delay')
    @override_switch('dsa-job-technical-processing', active=True)
    def test_reportable_reason_calls_cinder_task(self, task_mock):
        self._setup_reportable_reason('hateful_violent_deceptive')
        task_mock.assert_called()

    @mock.patch('olympia.abuse.tasks.report_to_cinder.delay')
    @override_switch('dsa-job-technical-processing', active=False)
    def test_reportable_reason_does_not_call_cinder_with_waffle_off(self, task_mock):
        self._setup_reportable_reason('hateful_violent_deceptive')
        task_mock.assert_not_called()

    @mock.patch('olympia.abuse.tasks.report_to_cinder.delay')
    @override_switch('dsa-job-technical-processing', active=True)
    def test_no_reason_does_not_call_cinder_task(self, task_mock):
        self._setup_reportable_reason(None, 'Some message since no reason is provided')
        task_mock.assert_not_called()

    def test_lang(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={
                'user': str(user.id),
                'message': 'abuse!',
                'lang': 'Lô-käl',
            },
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        report = AbuseReport.objects.get(user_id=user.id)
        self.check_report(report, f'Abuse Report for User {user.pk}')
        assert report.application_locale == 'Lô-käl'

    def test_reject_illegal_category_when_reason_is_not_illegal(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={
                'user': str(user.username),
                'reason': 'feedback_spam',
                'illegal_category': 'other',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': [
                'This value must be omitted or set to "null" when the `reason` is '
                'not "illegal".'
            ],
        }

    def test_reject_illegal_subcategory_when_reason_is_not_illegal(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={
                'user': str(user.username),
                'reason': 'feedback_spam',
                'illegal_subcategory': 'other',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': [
                'This value must be omitted or set to "null" when the `reason` is '
                'not "illegal".'
            ],
        }

    def test_illegal_category_required_when_reason_is_illegal(self):
        user = user_factory()
        response = self.client.post(
            self.url, data={'user': str(user.username), 'reason': 'illegal'}
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': ['This field is required.']
        }

    def test_illegal_category_cannot_be_blank_when_reason_is_illegal(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={
                'user': str(user.username),
                'reason': 'illegal',
                'illegal_category': '',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': ['"" is not a valid choice.']
        }

    def test_illegal_category_cannot_be_null_when_reason_is_illegal(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={
                'user': str(user.username),
                'reason': 'illegal',
                'illegal_category': None,
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': ['This field may not be null.']
        }

    def test_illegal_subcategory_required_when_reason_is_illegal(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={
                'user': str(user.username),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': ['This field is required.']
        }

    def test_illegal_subcategory_cannot_be_blank_when_reason_is_illegal(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={
                'user': str(user.username),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': '',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': ['"" is not a valid choice.']
        }

    def test_illegal_subcategory_cannot_be_null_when_reason_is_illegal(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={
                'user': str(user.username),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': None,
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': ['This field may not be null.']
        }

    def test_illegal_subcategory_depends_on_category(self):
        user = user_factory()
        response = self.client.post(
            self.url,
            data={
                'user': str(user.username),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'biometric_data_breach',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': [
                'This value cannot be used in combination with the supplied '
                '`illegal_category`.'
            ]
        }


class TestUserAbuseViewSetLoggedOut(UserAbuseViewSetTestBase, TestCase):
    def check_reporter(self, report):
        assert not report.reporter


class TestUserAbuseViewSetLoggedIn(UserAbuseViewSetTestBase, TestCase):
    def setUp(self):
        super().setUp()
        self.user = user_factory()
        self.client.login_api(self.user)

    def check_reporter(self, report):
        assert report.reporter == self.user

    def test_throttle_ip_for_authenticated_users(self):
        user = user_factory()
        self.client.login_api(user)
        target_user = user_factory()
        for x in range(20):
            response = self.client.post(
                self.url,
                data={'user': str(target_user.username), 'message': 'abuse!'},
                REMOTE_ADDR='123.45.67.89',
                HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
            )
            assert response.status_code == 201, x

        # Different user, same IP: should still be blocked (> 20 / day).
        new_user = user_factory()
        self.client.login_api(new_user)
        response = self.client.post(
            self.url,
            data={'user': str(target_user.username), 'message': 'abuse!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 429


@override_settings(CINDER_WEBHOOK_TOKEN='webhook-token')
@override_settings(CINDER_QUEUE_PREFIX='amo-')
class TestCinderWebhook(TestCase):
    def setUp(self):
        self.task_user = user_factory(pk=settings.TASK_USER_ID)

    def get_data(self, filename='decision.json'):
        webhook_file = os.path.join(
            TESTS_DIR, 'assets', 'cinder_webhook_payloads', filename
        )
        with open(webhook_file) as file_object:
            return json.loads(file_object.read())

    def _setup_reports(self):
        job_id = 'd16e1ebc-b6df-4742-83c1-61f5ed3bd644'
        guid = '1234'
        cinder_job = CinderJob.objects.create(job_id=job_id)
        return AbuseReport.objects.create(
            reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE,
            guid=guid,
            cinder_job=cinder_job,
        )

    def get_request(self, data):
        digest = hmac.new(
            b'webhook-token',
            msg=force_bytes(json.dumps(data, separators=(',', ':'))),
            digestmod=hashlib.sha256,
        ).hexdigest()
        req = APIRequestFactory().post(
            reverse_ns('cinder-webhook'),
            data,
            format='json',
            headers={'X_CINDER_SIGNATURE': digest},
        )
        return req

    def test_cinder_inbound_permission(self):
        permission = CinderInboundPermission()
        data = {'a': 'b'}
        digest = hmac.new(
            b'webhook-token', msg=b'{"a":"b"}', digestmod=hashlib.sha256
        ).hexdigest()

        assert not permission.has_permission(
            APIRequestFactory().post('/', data, format='json'), None
        )

        assert permission.has_permission(
            APIRequestFactory().post(
                '/',
                data,
                format='json',
                headers={'X_CINDER_SIGNATURE': digest},
            ),
            None,
        )

        assert not permission.has_permission(
            APIRequestFactory().post(
                '/',
                {**data, 'a': 'c'},
                format='json',
                headers={'X_CINDER_SIGNATURE': digest},
            ),
            None,
        )

    def test_filter_enforcement_actions(self):
        abuse_report = self._setup_reports()
        cinder_job = abuse_report.cinder_job
        addon_factory(guid=abuse_report.guid)
        assert filter_enforcement_actions([], cinder_job) == []
        actions_from_json = [
            'amo-disable_addon',
            'amo-ban-user',
            'amo-approve',
            'not-amo-action',  # not a valid action at all
        ]
        assert filter_enforcement_actions(actions_from_json, cinder_job) == [
            DECISION_ACTIONS.AMO_DISABLE_ADDON,
            # no AMO_BAN_USER action because not a user target
            DECISION_ACTIONS.AMO_APPROVE,
        ]

        # check with another content type too
        abuse_report.update(guid=None, user=user_factory())
        assert filter_enforcement_actions(actions_from_json, cinder_job) == [
            # no AMO_DISABLE_ADDON action because not an add-on target
            DECISION_ACTIONS.AMO_BAN_USER,
            DECISION_ACTIONS.AMO_APPROVE,
        ]

    def test_process_decision_called(
        self, data=None, *, slug='amo-content-infringement'
    ):
        abuse_report = self._setup_reports()
        addon_factory(guid=abuse_report.guid)
        req = self.get_request(data=data or self.get_data())
        with mock.patch.object(CinderJob, 'process_decision') as process_mock:
            response = cinder_webhook(req)
            process_mock.assert_called()
            process_mock.assert_called_with(
                decision_cinder_id='d1f01fae-3bce-41d5-af8a-e0b4b5ceaaed',
                decision_action=DECISION_ACTIONS.AMO_DISABLE_ADDON.value,
                decision_notes='some notes',
                policy_ids=['f73ad527-54ed-430c-86ff-80e15e2a352b'],
                job_queue=slug,
            )
        assert response.status_code == 201
        assert response.data == {'amo': {'received': True, 'handled': True}}

    def test_process_decision_decision_already_exists(self):
        abuse_report = self._setup_reports()
        addon_factory(guid=abuse_report.guid)
        req = self.get_request(data=self.get_data())
        with mock.patch.object(CinderJob, 'process_decision') as process_mock:
            process_mock.return_value = False
            response = cinder_webhook(req)
            process_mock.assert_called()
            process_mock.assert_called_with(
                decision_cinder_id='d1f01fae-3bce-41d5-af8a-e0b4b5ceaaed',
                decision_action=DECISION_ACTIONS.AMO_DISABLE_ADDON.value,
                decision_notes='some notes',
                policy_ids=['f73ad527-54ed-430c-86ff-80e15e2a352b'],
                job_queue='amo-content-infringement',
            )
        assert response.status_code == 200
        assert response.data == {
            'amo': {
                'received': True,
                'handled': False,
                'not_handled_reason': 'Decision already exists',
            }
        }

    def test_process_decision_called_for_appeal_confirm_approve(
        self, filename='reporter_appeal_confirm_approve.json'
    ):
        data = self.get_data(filename=filename)
        abuse_report = self._setup_reports()
        addon = addon_factory(guid=abuse_report.guid)
        original_cinder_job = CinderJob.objects.get()
        ContentDecision.objects.create(
            cinder_id='d1f01fae-3bce-41d5-af8a-e0b4b5ceaaed',
            action=DECISION_ACTIONS.AMO_APPROVE,
            appeal_job=CinderJob.objects.create(
                job_id='5c7c3e21-8ccd-4d2f-b3b4-429620bd7a63'
            ),
            addon=addon,
            cinder_job=original_cinder_job,
        )
        req = self.get_request(data=data)
        with mock.patch.object(CinderJob, 'process_decision') as process_mock:
            response = cinder_webhook(req)
        assert process_mock.call_count == 1
        process_mock.assert_called_with(
            decision_cinder_id='76e0006d-1a42-4ec7-9475-148bab1970f1',
            decision_action=DECISION_ACTIONS.AMO_APPROVE.value,
            decision_notes='still no!',
            policy_ids=['1c5d711a-78b7-4fc2-bdef-9a33024f5e8b'],
            job_queue='amo-dev-ratings',
        )
        assert response.status_code == 201
        assert response.data == {'amo': {'received': True, 'handled': True}}

    def test_process_decision_called_for_appeal_confirm_approve_with_override(self):
        """This is to cover the unusual case in cinder where a moderator processes an
        appeal by selecting to override the decision, but chooses to approve it again.
        """
        self.test_process_decision_called_for_appeal_confirm_approve(
            filename='reporter_appeal_change_but_still_approve.json'
        )

    def test_process_decision_called_for_appeal_change_to_disable(self):
        data = self.get_data(filename='reporter_appeal_change_to_disable.json')
        abuse_report = self._setup_reports()
        addon = addon_factory(guid=abuse_report.guid)
        original_cinder_job = CinderJob.objects.get()
        ContentDecision.objects.create(
            action_date=datetime(2023, 10, 12, 9, 8, 37, 4789),
            cinder_id='d1f01fae-3bce-41d5-af8a-e0b4b5ceaaed',
            action=DECISION_ACTIONS.AMO_APPROVE,
            appeal_job=CinderJob.objects.create(
                job_id='5ab7cb33-a5ab-4dfa-9d72-4c2061ffeb08'
            ),
            addon=addon,
            cinder_job=original_cinder_job,
        )
        req = self.get_request(data=data)
        with mock.patch.object(CinderJob, 'process_decision') as process_mock:
            response = cinder_webhook(req)
        assert process_mock.call_count == 1
        process_mock.assert_called_with(
            decision_cinder_id='4f18b22c-6078-4934-b395-6a2e01cadf63',
            decision_action=DECISION_ACTIONS.AMO_DISABLE_ADDON.value,
            decision_notes="fine I'll disable it",
            policy_ids=[
                '7ea512a2-39a6-4cb6-91a0-2ed162192f7f',
                'a5c96c92-2373-4d11-b573-61b0de00d8e0',
            ],
            job_queue='amo-dev-ratings',
        )
        assert response.status_code == 201
        assert response.data == {'amo': {'received': True, 'handled': True}}

    def test_process_decision_called_for_override_to_approve(self):
        abuse_report = self._setup_reports()
        ContentDecision.objects.create(
            cinder_id='d1f01fae-3bce-41d5-af8a-e0b4b5ceaaed',
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon_factory(guid=abuse_report.guid),
            cinder_job=CinderJob.objects.get(),
            from_job_queue='queue-for-original-decision',
        )
        req = self.get_request(
            data=self.get_data(filename='override_change_to_approve.json')
        )
        with mock.patch.object(CinderJob, 'process_decision') as process_mock:
            response = cinder_webhook(req)
        assert process_mock.call_count == 1, response.data
        process_mock.assert_called_with(
            decision_cinder_id='3eacdc09-c292-4fcb-a56f-a3d45d5eefeb',
            decision_action=DECISION_ACTIONS.AMO_APPROVE.value,
            decision_notes='changed our mind',
            policy_ids=['085f6a1c-46b6-44c2-a6ae-c3a73488aa1e'],
            job_queue='queue-for-original-decision',
        )
        assert response.status_code == 201
        assert response.data == {'amo': {'received': True, 'handled': True}}

    def test_process_decision_triggers_emails_when_disable_confirmed(self):
        data = self.get_data(filename='target_appeal_confirm_disable.json')
        abuse_report = self._setup_reports()
        author = user_factory()
        addon = addon_factory(guid=abuse_report.guid, users=[author])
        original_cinder_job = CinderJob.objects.get()
        ContentDecision.objects.create(
            action_date=datetime(2023, 10, 12, 9, 8, 37, 4789),
            cinder_id='d1f01fae-3bce-41d5-af8a-e0b4b5ceaaed',
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            appeal_job=CinderJob.objects.create(
                job_id='5ab7cb33-a5ab-4dfa-9d72-4c2061ffeb08'
            ),
            addon=addon,
            cinder_job=original_cinder_job,
        )
        req = self.get_request(data=data)
        with mock.patch.object(
            ContentActionTargetAppealRemovalAffirmation, 'process_action'
        ) as process_mock:
            cinder_webhook(req)
        process_mock.assert_called()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [author.email]
        assert 'will not reinstate your Extension' in mail.outbox[0].body

    def test_process_decision_triggers_emails_when_disable_reverted(self):
        data = self.get_data(filename='target_appeal_change_to_approve.json')
        abuse_report = self._setup_reports()
        author = user_factory()
        addon = addon_factory(guid=abuse_report.guid, users=[author])
        original_cinder_job = CinderJob.objects.get()
        ContentDecision.objects.create(
            action_date=datetime(2023, 10, 12, 9, 8, 37, 4789),
            cinder_id='d1f01fae-3bce-41d5-af8a-e0b4b5ceaaed',
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            appeal_job=CinderJob.objects.create(
                job_id='5ab7cb33-a5ab-4dfa-9d72-4c2061ffeb08'
            ),
            addon=addon,
            cinder_job=original_cinder_job,
        )
        req = self.get_request(data=data)
        with mock.patch.object(
            ContentActionTargetAppealApprove, 'process_action'
        ) as process_mock:
            cinder_webhook(req)
        process_mock.assert_called()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [author.email]
        assert 'we have restored your Extension' in mail.outbox[0].body

    def test_process_decision_triggers_emails_for_reporter_appeal_disable(self):
        data = self.get_data(filename='reporter_appeal_change_to_disable.json')
        abuse_report = self._setup_reports()
        author = user_factory()
        addon = addon_factory(guid=abuse_report.guid, users=[author])
        original_cinder_job = CinderJob.objects.get()
        ContentDecision.objects.create(
            action_date=datetime(2023, 10, 12, 9, 8, 37, 4789),
            cinder_id='d1f01fae-3bce-41d5-af8a-e0b4b5ceaaed',
            action=DECISION_ACTIONS.AMO_APPROVE,
            appeal_job=CinderJob.objects.create(
                job_id='5ab7cb33-a5ab-4dfa-9d72-4c2061ffeb08'
            ),
            addon=addon,
            cinder_job=original_cinder_job,
        )
        abuse_report.update(
            reporter_email='reporter@email.com', cinder_job=original_cinder_job
        )
        CinderAppeal.objects.create(
            decision=original_cinder_job.decision, reporter_report=abuse_report
        )
        req = self.get_request(data=data)
        with mock.patch.object(
            ContentActionDisableAddon, 'process_action'
        ) as process_mock:
            cinder_webhook(req)
        process_mock.assert_called()
        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == ['reporter@email.com']
        assert 'was incorrect' in mail.outbox[0].body
        assert mail.outbox[1].to == [author.email]
        assert 'has been permanently disabled' in mail.outbox[1].body

    def test_process_decision_triggers_no_target_email_for_reporter_approve(self):
        data = self.get_data(filename='reporter_appeal_confirm_approve.json')
        abuse_report = self._setup_reports()
        author = user_factory()
        addon = addon_factory(guid=abuse_report.guid, users=[author])
        original_cinder_job = CinderJob.objects.get()
        ContentDecision.objects.create(
            action_date=datetime(2023, 10, 12, 9, 8, 37, 4789),
            cinder_id='d1f01fae-3bce-41d5-af8a-e0b4b5ceaaed',
            action=DECISION_ACTIONS.AMO_APPROVE,
            appeal_job=CinderJob.objects.create(
                job_id='5c7c3e21-8ccd-4d2f-b3b4-429620bd7a63'
            ),
            addon=addon,
            cinder_job=original_cinder_job,
        )
        abuse_report.update(
            reporter_email='reporter@email.com', cinder_job=original_cinder_job
        )
        CinderAppeal.objects.create(
            decision=original_cinder_job.decision, reporter_report=abuse_report
        )
        req = self.get_request(data=data)
        with mock.patch.object(
            ContentActionApproveNoAction, 'process_action'
        ) as process_mock:
            cinder_webhook(req)
        process_mock.assert_called()
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['reporter@email.com']
        assert 'we have denied your appeal' in mail.outbox[0].body

    def test_queue_does_not_matter_non_reviewer_case(self):
        data = self.get_data()
        slug = 'amo-another-queue'
        data['payload']['source']['job']['queue']['slug'] = slug
        return self.test_process_decision_called(data, slug=slug)

    def test_unknown_event(self):
        self._setup_reports()
        data = self.get_data()
        data['event'] = 'report.created'
        req = self.get_request(data=data)
        with mock.patch.object(CinderJob, 'process_decision') as process_mock:
            response = cinder_webhook(req)
            process_mock.assert_not_called()
        assert response.status_code == 400
        assert response.data == {
            'amo': {
                'received': True,
                'handled': False,
                'not_handled_reason': 'report.created is not a event we support',
            }
        }

    def test_missing_payload(self):
        expected = {
            'amo': {
                'received': True,
                'handled': False,
                'not_handled_reason': 'No payload dict',
            }
        }

        def check(response):
            process_mock.assert_not_called()
            assert response.status_code == 400
            assert response.data == expected

        self._setup_reports()
        data = self.get_data()
        with mock.patch.object(CinderJob, 'process_decision') as process_mock:
            del data['payload']
            check(cinder_webhook(self.get_request(data=data)))
            data['payload'] = 'string'
            check(cinder_webhook(self.get_request(data=data)))
            data['payload'] = {}
            check(cinder_webhook(self.get_request(data=data)))

    def _test_no_cinder_job(self, status_code):
        req = self.get_request(data=self.get_data())
        with mock.patch.object(CinderJob, 'process_decision') as process_mock:
            response = cinder_webhook(req)
            process_mock.assert_not_called()
        assert response.status_code == status_code
        assert response.data == {
            'amo': {
                'received': True,
                'handled': False,
                'not_handled_reason': 'No matching job id found',
            }
        }

    def test_no_cinder_job_nonprod(self):
        with override_settings(CINDER_UNIQUE_IDS=False):
            self._test_no_cinder_job(200)

    def test_no_cinder_job_prod(self):
        with override_settings(CINDER_UNIQUE_IDS=True):
            self._test_no_cinder_job(400)

    def _test_unknown_decision_for_override(self, status_code):
        req = self.get_request(
            data=self.get_data(filename='override_change_to_approve.json')
        )
        with mock.patch.object(CinderJob, 'process_decision') as process_mock:
            response = cinder_webhook(req)
            process_mock.assert_not_called()
        assert response.status_code == status_code
        assert response.data == {
            'amo': {
                'received': True,
                'handled': False,
                'not_handled_reason': 'No matching decision id found',
            }
        }

    def test_no_decision_noprod(self):
        with override_settings(CINDER_UNIQUE_IDS=False):
            self._test_unknown_decision_for_override(200)

    def test_no_decision_prod(self):
        with override_settings(CINDER_UNIQUE_IDS=True):
            self._test_unknown_decision_for_override(400)

    def _test_valid_decision_but_no_cinder_job(self, status_code):
        abuse_report = self._setup_reports()
        ContentDecision.objects.create(
            cinder_id='d1f01fae-3bce-41d5-af8a-e0b4b5ceaaed',
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon_factory(guid=abuse_report.guid),
        )
        req = self.get_request(
            data=self.get_data(filename='override_change_to_approve.json')
        )
        with mock.patch.object(CinderJob, 'process_decision') as process_mock:
            response = cinder_webhook(req)
            process_mock.assert_not_called()
        assert response.status_code == status_code
        assert response.data == {
            'amo': {
                'received': True,
                'handled': False,
                'not_handled_reason': 'No matching job found for decision id',
            }
        }

    def test_valid_decision_but_no_cinder_job_nonprod(self):
        with override_settings(CINDER_UNIQUE_IDS=False):
            self._test_valid_decision_but_no_cinder_job(200)

    def test_valid_decision_but_no_cinder_job_prod(self):
        with override_settings(CINDER_UNIQUE_IDS=True):
            self._test_valid_decision_but_no_cinder_job(400)

    def test_reviewer_tools_resolved_decision(self):
        data = self.get_data(filename='proactive_decision_from_amo.json')
        self._setup_reports()
        req = self.get_request(data=data)
        with mock.patch.object(CinderJob, 'process_decision') as process_mock:
            response = cinder_webhook(req)
            process_mock.assert_not_called()
        assert response.status_code == 200
        assert response.data == {
            'amo': {
                'received': True,
                'handled': False,
                'not_handled_reason': 'Decision already handled via reviewer tools',
            }
        }

    def test_proactive_decision_from_cinder(self):
        data = self.get_data(filename='proactive_decision_from_amo.json')
        data['payload']['source']['decision']['type'] = 'queue_review'
        self._setup_reports()
        req = self.get_request(data=data)
        with mock.patch.object(CinderJob, 'process_decision') as process_mock:
            response = cinder_webhook(req)
            process_mock.assert_not_called()
        assert response.status_code == 400
        assert response.data == {
            'amo': {
                'received': True,
                'handled': False,
                'not_handled_reason': 'Unsupported Manual decision',
            }
        }

    def test_invalid_decision_action(self):
        abuse_report = self._setup_reports()
        addon_factory(guid=abuse_report.guid)
        data = self.get_data()

        data['payload']['enforcement_actions'] = []
        response = cinder_webhook(self.get_request(data=data))
        assert response.status_code == 400
        assert response.data == {
            'amo': {
                'received': True,
                'handled': False,
                'not_handled_reason': (
                    'Payload invalid: no supported enforcement_actions'
                ),
            }
        }

        data['payload']['enforcement_actions'] = ['unknown_action']
        response = cinder_webhook(self.get_request(data=data))
        assert response.status_code == 400
        assert response.data == {
            'amo': {
                'received': True,
                'handled': False,
                'not_handled_reason': (
                    'Payload invalid: no supported enforcement_actions'
                ),
            }
        }

        data['payload']['enforcement_actions'] = [
            'amo-disable-addon',
            'amo-escalate-addon',
        ]
        response = cinder_webhook(self.get_request(data=data))
        assert response.status_code == 400
        assert response.data == {
            'amo': {
                'received': True,
                'handled': False,
                'not_handled_reason': (
                    'Payload invalid: more than one supported enforcement_actions'
                ),
            }
        }

    def test_process_queue_move_called(self):
        abuse_report = self._setup_reports()
        addon_factory(guid=abuse_report.guid)
        req = self.get_request(
            data=self.get_data('job_actioned_move_to_dev_infringement.json')
        )
        with mock.patch.object(CinderJob, 'process_queue_move') as process_mock:
            response = cinder_webhook(req)
            process_mock.assert_called()
            process_mock.assert_called_with(
                new_queue='amo-env-addon-infringement', notes='no'
            )
        assert response.status_code == 201
        assert response.data == {'amo': {'received': True, 'handled': True}}

    def _test_process_queue_move_no_cinder_report(self, status_code):
        req = self.get_request(
            data=self.get_data('job_actioned_move_to_dev_infringement.json')
        )
        with mock.patch.object(CinderJob, 'process_queue_move') as process_mock:
            response = cinder_webhook(req)
            process_mock.assert_not_called()
        assert response.status_code == status_code
        assert response.data == {
            'amo': {
                'received': True,
                'handled': False,
                'not_handled_reason': 'No matching job id found',
            }
        }

    def test_process_queue_move_no_cinder_report_nonprod(self):
        with override_settings(CINDER_UNIQUE_IDS=False):
            self._test_process_queue_move_no_cinder_report(200)

    def test_process_queue_move_no_cinder_report_prod(self):
        with override_settings(CINDER_UNIQUE_IDS=True):
            self._test_process_queue_move_no_cinder_report(400)

    def test_process_queue_move_invalid_action(self):
        data = self.get_data('job_actioned_move_to_dev_infringement.json')

        data['payload']['action'] = 'something_else'
        response = cinder_webhook(self.get_request(data=data))
        assert response.status_code == 400
        assert response.data == {
            'amo': {
                'received': True,
                'handled': False,
                'not_handled_reason': (
                    'Unsupported action (something_else) for job.actioned'
                ),
            }
        }

    def test_process_queue_move_not_addon(self):
        data = self.get_data('job_actioned_move_to_dev_infringement.json')

        data['payload']['job']['entity']['entity_schema'] = 'amo_user'
        response = cinder_webhook(self.get_request(data=data))
        assert response.status_code == 200
        assert response.data == {
            'amo': {
                'received': True,
                'handled': False,
                'not_handled_reason': (
                    'Unsupported entity_schema (amo_user) for job.actioned'
                ),
            }
        }

    def test_set_user(self):
        set_user(user_factory())
        req = self.get_request(data=self.get_data())
        response = cinder_webhook(req)
        assert response.status_code == 200
        assert get_user() == self.task_user


class RatingAbuseViewSetTestBase:
    client_class = APITestClientSessionID

    def setUp(self):
        self.url = reverse_ns('abusereportrating-list')

    def check_reporter(self, report):
        raise NotImplementedError

    def check_report(self, report, text):
        assert str(report) == text
        self.check_reporter(report)

    def test_report_rating_id(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'message': 'abuse!',
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(rating_id=target_rating.pk).exists()
        report = AbuseReport.objects.get(rating=target_rating)
        self.check_report(report, f'Abuse Report for Rating {target_rating.pk}')

    def test_report_rating_id_int(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={
                'rating': target_rating.pk,
                'message': 'abuse!',
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(rating_id=target_rating.pk).exists()
        report = AbuseReport.objects.get(rating=target_rating)
        self.check_report(report, f'Abuse Report for Rating {target_rating.pk}')

    def test_no_rating_fails(self):
        response = self.client.post(
            self.url,
            data={
                'message': 'abuse!',
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {'rating': ['This field is required.']}

    def test_only_reasons_accepted_are_content_subset(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'message': 'foo',
                'reason': 'does_not_work',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'reason': ['"does_not_work" is not a valid choice.']
        }

    def test_message_can_be_blank_if_reason_is_provided(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'message': '',
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
        )
        assert response.status_code == 201

    def test_message_can_be_missing_if_reason_is_provided(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
        )
        assert response.status_code == 201

    def test_message_required_empty_no_reason_provided(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={'rating': str(target_rating.pk), 'message': ''},
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'message': ['This field may not be blank.']
        }

    def test_message_required_missing_no_reason_provided(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(self.url, data={'rating': str(target_rating.pk)})
        assert response.status_code == 400
        assert json.loads(response.content) == {'message': ['This field is required.']}

    def test_throttle(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        for x in range(20):
            response = self.client.post(
                self.url,
                data={
                    'rating': str(target_rating.pk),
                    'message': 'abuse!',
                    'reason': 'illegal',
                    'illegal_category': 'animal_welfare',
                    'illegal_subcategory': 'other',
                },
                REMOTE_ADDR='123.45.67.89',
                HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
            )
            assert response.status_code == 201, x

        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'message': 'abuse!',
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 429

    def test_report_country_code(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'message': 'abuse!',
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_COUNTRY_CODE='YY',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(rating_id=target_rating.pk).exists()
        report = AbuseReport.objects.get(rating=target_rating)
        self.check_report(report, f'Abuse Report for Rating {target_rating.pk}')
        assert report.country_code == 'YY'

    def _setup_reportable_reason(self, reason):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={'rating': target_rating.pk, 'reason': reason, 'message': 'bad!'},
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201, response.content

    @mock.patch('olympia.abuse.tasks.report_to_cinder.delay')
    @override_switch('dsa-job-technical-processing', active=True)
    def test_reportable_reason_calls_cinder_task(self, task_mock):
        self._setup_reportable_reason('hateful_violent_deceptive')
        task_mock.assert_called()

    @mock.patch('olympia.abuse.tasks.report_to_cinder.delay')
    @override_switch('dsa-job-technical-processing', active=False)
    def test_reportable_reason_does_not_call_cinder_with_waffle_off(self, task_mock):
        self._setup_reportable_reason('hateful_violent_deceptive')
        task_mock.assert_not_called()

    def test_lang(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'message': 'abuse!',
                'reason': 'illegal',
                'lang': 'Lô-käl',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        report = AbuseReport.objects.get(rating=target_rating)
        self.check_report(report, f'Abuse Report for Rating {target_rating.pk}')
        assert report.application_locale == 'Lô-käl'

    def test_reject_illegal_category_when_reason_is_not_illegal(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'reason': 'feedback_spam',
                'illegal_category': 'other',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': [
                'This value must be omitted or set to "null" when the `reason` is '
                'not "illegal".'
            ],
        }

    def test_reject_illegal_subcategory_when_reason_is_not_illegal(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'reason': 'feedback_spam',
                'illegal_subcategory': 'other',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': [
                'This value must be omitted or set to "null" when the `reason` is '
                'not "illegal".'
            ],
        }

    def test_illegal_category_required_when_reason_is_illegal(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url, data={'rating': str(target_rating.pk), 'reason': 'illegal'}
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': ['This field is required.']
        }

    def test_illegal_category_cannot_be_blank_when_reason_is_illegal(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'reason': 'illegal',
                'illegal_category': '',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': ['"" is not a valid choice.']
        }

    def test_illegal_category_cannot_be_null_when_reason_is_illegal(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'reason': 'illegal',
                'illegal_category': None,
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': ['This field may not be null.']
        }

    def test_illegal_subcategory_required_when_reason_is_illegal(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': ['This field is required.']
        }

    def test_illegal_subcategory_cannot_be_blank_when_reason_is_illegal(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': '',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': ['"" is not a valid choice.']
        }

    def test_illegal_subcategory_cannot_be_null_when_reason_is_illegal(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(),
            user=user_factory(),
            body='Booh',
            rating=1,
        )
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': None,
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': ['This field may not be null.']
        }

    def test_illegal_subcategory_depends_on_category(self):
        target_rating = Rating.objects.create(
            addon=addon_factory(),
            user=user_factory(),
            body='Booh',
            rating=1,
        )
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'biometric_data_breach',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': [
                'This value cannot be used in combination with the supplied '
                '`illegal_category`.'
            ]
        }


class TestRatingAbuseViewSetLoggedOut(RatingAbuseViewSetTestBase, TestCase):
    def check_reporter(self, report):
        assert not report.reporter


class TestRatingAbuseViewSetLoggedIn(RatingAbuseViewSetTestBase, TestCase):
    def setUp(self):
        super().setUp()
        self.user = user_factory()
        self.client.login_api(self.user)

    def check_reporter(self, report):
        assert report.reporter == self.user

    def test_throttle_ip_for_authenticated_users(self):
        user = user_factory()
        self.client.login_api(user)
        target_rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(), body='Booh', rating=1
        )
        for x in range(20):
            response = self.client.post(
                self.url,
                data={
                    'rating': str(target_rating.pk),
                    'message': 'abuse!',
                    'reason': 'illegal',
                    'illegal_category': 'animal_welfare',
                    'illegal_subcategory': 'other',
                },
                REMOTE_ADDR='123.45.67.89',
                HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
            )
            assert response.status_code == 201, x

        # Different user, same IP: should still be blocked (> 20 / day).
        new_user = user_factory()
        self.client.login_api(new_user)
        response = self.client.post(
            self.url,
            data={
                'rating': str(target_rating.pk),
                'message': 'abuse!',
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 429


class CollectionAbuseViewSetTestBase:
    client_class = APITestClientSessionID

    def setUp(self):
        self.url = reverse_ns('abusereportcollection-list')

    def check_reporter(self, report):
        raise NotImplementedError

    def check_report(self, report, text):
        assert str(report) == text
        self.check_reporter(report)

    def test_report_collection_id(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'message': 'abusé!',
                'reason': 'hateful_violent_deceptive',
            },
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(collection_id=target_collection.pk).exists()
        report = AbuseReport.objects.get(collection=target_collection)
        self.check_report(report, f'Abuse Report for Collection {target_collection.pk}')

    def test_report_collection_id_int(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': target_collection.pk,
                'message': 'abusé!',
                'reason': 'hateful_violent_deceptive',
            },
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(collection_id=target_collection.pk).exists()
        report = AbuseReport.objects.get(collection=target_collection)
        self.check_report(report, f'Abuse Report for Collection {target_collection.pk}')

    def test_no_collection_fails(self):
        response = self.client.post(
            self.url, data={'message': 'abusë!', 'reason': 'hateful_violent_deceptive'}
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'collection': ['This field is required.']
        }

    def test_only_reasons_accepted_are_content_subset(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'message': 'foo',
                'reason': 'does_not_work',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'reason': ['"does_not_work" is not a valid choice.']
        }

    def test_message_can_be_blank_if_reason_is_provided(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'message': '',
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
        )
        assert response.status_code == 201

    def test_message_can_be_missing_if_reason_is_provided(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
        )
        assert response.status_code == 201

    def test_message_required_empty_no_reason_provided(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={'collection': str(target_collection.pk), 'message': ''},
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'message': ['This field may not be blank.']
        }

    def test_message_required_missing_no_reason_provided(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url, data={'collection': str(target_collection.pk)}
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {'message': ['This field is required.']}

    def test_throttle(self):
        target_collection = collection_factory()
        for x in range(20):
            response = self.client.post(
                self.url,
                data={
                    'collection': str(target_collection.pk),
                    'message': 'abuse!',
                    'reason': 'illegal',
                    'illegal_category': 'animal_welfare',
                    'illegal_subcategory': 'other',
                },
                REMOTE_ADDR='123.45.67.89',
                HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
            )
            assert response.status_code == 201, x

        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'message': 'abuse!',
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 429

    def test_report_country_code(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'message': 'abuse!',
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_COUNTRY_CODE='YY',
        )
        assert response.status_code == 201

        assert AbuseReport.objects.filter(collection_id=target_collection.pk).exists()
        report = AbuseReport.objects.get(collection=target_collection)
        self.check_report(report, f'Abuse Report for Collection {target_collection.pk}')
        assert report.country_code == 'YY'

    def _setup_reportable_reason(self, reason):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': target_collection.pk,
                'reason': reason,
                'message': 'bad!',
            },
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 201, response.content

    @mock.patch('olympia.abuse.tasks.report_to_cinder.delay')
    @override_switch('dsa-job-technical-processing', active=True)
    def test_reportable_reason_calls_cinder_task(self, task_mock):
        self._setup_reportable_reason('hateful_violent_deceptive')
        task_mock.assert_called()

    @mock.patch('olympia.abuse.tasks.report_to_cinder.delay')
    @override_switch('dsa-job-technical-processing', active=False)
    def test_reportable_reason_does_not_call_cinder_with_waffle_off(self, task_mock):
        self._setup_reportable_reason('hateful_violent_deceptive')
        task_mock.assert_not_called()

    def test_lang(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'message': 'abusé!',
                'reason': 'hateful_violent_deceptive',
                'lang': 'Lô-käl',
            },
            REMOTE_ADDR='123.45.67.89',
        )
        assert response.status_code == 201

        report = AbuseReport.objects.get(collection=target_collection)
        self.check_report(report, f'Abuse Report for Collection {target_collection.pk}')
        assert report.application_locale == 'Lô-käl'

    def test_reject_illegal_category_when_reason_is_not_illegal(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'reason': 'feedback_spam',
                'illegal_category': 'other',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': [
                'This value must be omitted or set to "null" when the `reason` is '
                'not "illegal".'
            ],
        }

    def test_reject_illegal_subcategory_when_reason_is_not_illegal(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'reason': 'feedback_spam',
                'illegal_subcategory': 'other',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': [
                'This value must be omitted or set to "null" when the `reason` is '
                'not "illegal".'
            ],
        }

    def test_illegal_category_required_when_reason_is_illegal(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={'collection': str(target_collection.pk), 'reason': 'illegal'},
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': ['This field is required.']
        }

    def test_illegal_category_cannot_be_blank_when_reason_is_illegal(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'reason': 'illegal',
                'illegal_category': '',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': ['"" is not a valid choice.']
        }

    def test_illegal_category_cannot_be_null_when_reason_is_illegal(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'reason': 'illegal',
                'illegal_category': None,
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_category': ['This field may not be null.']
        }

    def test_illegal_subcategory_required_when_reason_is_illegal(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': ['This field is required.']
        }

    def test_illegal_subcategory_cannot_be_blank_when_reason_is_illegal(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': '',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': ['"" is not a valid choice.']
        }

    def test_illegal_subcategory_cannot_be_null_when_reason_is_illegal(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': None,
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': ['This field may not be null.']
        }

    def test_illegal_subcategory_depends_on_category(self):
        target_collection = collection_factory()
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'biometric_data_breach',
            },
        )
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'illegal_subcategory': [
                'This value cannot be used in combination with the supplied '
                '`illegal_category`.'
            ]
        }


class TestCollectionAbuseViewSetLoggedOut(CollectionAbuseViewSetTestBase, TestCase):
    def check_reporter(self, report):
        assert not report.reporter


class TestCollectionAbuseViewSetLoggedIn(CollectionAbuseViewSetTestBase, TestCase):
    def setUp(self):
        super().setUp()
        self.user = user_factory()
        self.client.login_api(self.user)

    def check_reporter(self, report):
        assert report.reporter == self.user

    def test_throttle_ip_for_authenticated_users(self):
        user = user_factory()
        self.client.login_api(user)
        target_collection = collection_factory()
        for x in range(20):
            response = self.client.post(
                self.url,
                data={
                    'collection': str(target_collection.pk),
                    'message': 'abuse!',
                    'reason': 'illegal',
                    'illegal_category': 'animal_welfare',
                    'illegal_subcategory': 'other',
                },
                REMOTE_ADDR='123.45.67.89',
                HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
            )
            assert response.status_code == 201, x

        # Different user, same IP: should still be blocked (> 20 / day).
        new_user = user_factory()
        self.client.login_api(new_user)
        response = self.client.post(
            self.url,
            data={
                'collection': str(target_collection.pk),
                'message': 'abuse!',
                'reason': 'illegal',
                'illegal_category': 'animal_welfare',
                'illegal_subcategory': 'other',
            },
            REMOTE_ADDR='123.45.67.89',
            HTTP_X_FORWARDED_FOR=f'123.45.67.89, {get_random_ip()}',
        )
        assert response.status_code == 429


class TestAppeal(TestCase):
    def setUp(self):
        self.addon = addon_factory()
        self.cinder_job = CinderJob.objects.create(
            decision=ContentDecision.objects.create(
                cinder_id='my-decision-id',
                action=DECISION_ACTIONS.AMO_APPROVE,
                action_date=self.days_ago(1),
                addon=self.addon,
            ),
            created=self.days_ago(2),
        )
        self.abuse_report = AbuseReport.objects.create(
            reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE,
            guid=self.addon.guid,
            created=self.cinder_job.created,
            cinder_job=self.cinder_job,
        )
        self.reporter_appeal_url = reverse(
            'abuse.appeal_reporter',
            kwargs={
                'abuse_report_id': self.abuse_report.id,
                'decision_cinder_id': self.cinder_job.decision.cinder_id,
            },
        )
        self.author_appeal_url = reverse(
            'abuse.appeal_author',
            kwargs={
                'decision_cinder_id': self.cinder_job.decision.cinder_id,
            },
        )
        patcher = mock.patch('olympia.abuse.views.appeal_to_cinder')
        self.addCleanup(patcher.stop)
        self.appeal_mock = patcher.start()

    def test_no_decision_yet(self):
        self.cinder_job.decision.delete()
        assert self.client.get(self.reporter_appeal_url).status_code == 404
        assert self.client.get(self.author_appeal_url).status_code == 404

    def test_no_such_decision(self):
        url = reverse(
            'abuse.appeal_reporter',
            kwargs={
                'abuse_report_id': self.abuse_report.id,
                'decision_cinder_id': '1234-5678-9000',
            },
        )
        assert self.client.get(url).status_code == 404

        url = reverse(
            'abuse.appeal_author',
            kwargs={
                'decision_cinder_id': '1234-5678-9000',
            },
        )
        assert self.client.get(url).status_code == 404

    def test_no_such_abuse_report(self):
        url = reverse(
            'abuse.appeal_reporter',
            kwargs={
                'abuse_report_id': self.abuse_report.id + 1,
                'decision_cinder_id': self.cinder_job.decision.cinder_id,
            },
        )
        assert self.client.get(url).status_code == 404

    def test_appeal_approval_anonymous_report_with_no_email(self):
        response = self.client.get(self.reporter_appeal_url)
        assert response.status_code == 403

    def test_appeal_approval_anonymous_report_with_email(self):
        self.abuse_report.update(reporter_email='me@example.com')
        response = self.client.get(self.reporter_appeal_url)
        assert response.status_code == 200
        doc = pq(response.content)
        email_input = doc('#id_email')[0]
        assert email_input.type == 'email'
        assert email_input.label.text == 'Email address:'
        assert not doc('#appeal-thank-you')
        assert not doc('#id_reason')
        assert doc('#appeal-submit')
        assert self.appeal_mock.call_count == 0

    def test_appeal_approval_anonymous_report_with_email_post_invalid(self):
        self.abuse_report.update(reporter_email='me@example.com')
        response = self.client.post(
            self.reporter_appeal_url, {'email': 'absolutelynotme@example.com'}
        )
        assert response.status_code == 200
        doc = pq(response.content)
        email_input = doc('#id_email')[0]
        assert email_input.type == 'email'
        assert doc('ul.errorlist').text() == 'Invalid email provided.'
        assert not doc('#id_reason')
        assert not doc('#appeal-thank-you')
        assert doc('#appeal-submit')
        assert self.appeal_mock.call_count == 0

    def test_appeal_approval_anonymous_report_with_email_post(self):
        self.abuse_report.update(reporter_email='me@example.com')
        response = self.client.post(
            self.reporter_appeal_url, {'email': 'me@example.com'}
        )
        assert response.status_code == 200
        doc = pq(response.content)
        email_input = doc('#id_email')[0]
        assert email_input.type == 'hidden'
        assert doc('#id_reason')
        assert not doc('#appeal-thank-you')
        assert doc('#appeal-submit')
        assert self.appeal_mock.call_count == 0

        response = self.client.post(
            self.reporter_appeal_url,
            {'email': 'me@example.com', 'reason': 'I dont like this'},
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#appeal-thank-you')
        assert not doc('#id_reason')
        assert not doc('#appeal-submit')
        assert self.appeal_mock.delay.call_count == 1
        assert self.appeal_mock.delay.call_args_list[0][0] == ()
        assert self.appeal_mock.delay.call_args_list[0][1] == {
            'appeal_text': 'I dont like this',
            'decision_cinder_id': self.cinder_job.decision.cinder_id,
            'abuse_report_id': self.abuse_report.id,
            'user_id': None,
            'is_reporter': True,
        }

    def test_appeal_approval_anonymous_report_with_email_post_cant_be_appealed(self):
        self.cinder_job.decision.update(action_date=self.days_ago(200))
        self.abuse_report.update(reporter_email='me@example.com')
        response = self.client.get(self.reporter_appeal_url)
        assert response.status_code == 200
        doc = pq(response.content)
        email_input = doc('#id_email')[0]
        assert email_input.type == 'email'
        assert not doc('#id_reason')
        assert not doc('#appeal-thank-you')
        # Before an email has been entered and checked, we don't reveal whether
        # the decision can be appealed.
        assert "This decision can't be appealed" not in doc.text()
        assert doc('#appeal-submit')
        assert self.appeal_mock.call_count == 0

        response = self.client.post(
            self.reporter_appeal_url, {'email': 'me@example.com'}
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#id_email')
        assert not doc('#appeal-thank-you')
        assert not doc('#id_reason')
        assert not doc('#appeal-submit')
        assert "This decision can't be appealed" in doc.text()
        assert self.appeal_mock.call_count == 0

    def test_appeal_approval_logged_in_report_redirect_to_login(self):
        self.user = user_factory()
        self.abuse_report.update(reporter=self.user)
        response = self.client.get(self.reporter_appeal_url)
        self.assertLoginRedirects(response, self.reporter_appeal_url)

    def test_appeal_approval_logged_in_report_wrong_user(self):
        self.user = user_factory()
        self.abuse_report.update(reporter=self.user)
        self.user2 = user_factory()
        self.client.force_login(self.user2)
        response = self.client.get(self.reporter_appeal_url)
        assert response.status_code == 403

    def test_appeal_approval_loggued_in_user(self):
        self.user = user_factory()
        self.abuse_report.update(reporter=self.user)
        self.client.force_login(self.user)
        response = self.client.get(self.reporter_appeal_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#id_email')
        assert not doc('#appeal-thank-you')
        assert doc('#id_reason')
        assert doc('#appeal-submit')
        assert self.appeal_mock.call_count == 0

    def test_appeal_approval_logged_in_report_cant_be_appealed(self):
        self.cinder_job.decision.update(action_date=self.days_ago(200))
        self.user = user_factory()
        self.abuse_report.update(reporter=self.user)
        self.client.force_login(self.user)
        response = self.client.get(self.reporter_appeal_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#id_email')
        assert not doc('#appeal-thank-you')
        assert not doc('#id_reason')
        assert not doc('#appeal-submit')
        assert "This decision can't be appealed" in doc.text()
        assert self.appeal_mock.call_count == 0

    def test_appeal_rejection_not_logged_in(self):
        self.cinder_job.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        response = self.client.get(self.author_appeal_url)
        self.assertLoginRedirects(response, self.author_appeal_url)

    def test_appeal_rejection_not_author(self):
        self.cinder_job.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        user = user_factory()
        self.client.force_login(user)
        response = self.client.get(self.author_appeal_url)
        assert response.status_code == 403

    def test_appeal_rejection_author(self):
        self.cinder_job.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        user = user_factory()
        self.addon.authors.add(user)
        self.client.force_login(user)
        response = self.client.get(self.author_appeal_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#id_email')
        assert not doc('#appeal-thank-you')
        assert doc('#id_reason')
        assert doc('#appeal-submit')

        response = self.client.post(
            self.author_appeal_url,
            {'email': 'me@example.com', 'reason': 'I dont like this'},
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#appeal-thank-you')
        assert not doc('#id_reason')
        assert not doc('#appeal-submit')
        assert self.appeal_mock.delay.call_count == 1
        assert self.appeal_mock.delay.call_args_list[0][0] == ()
        assert self.appeal_mock.delay.call_args_list[0][1] == {
            'appeal_text': 'I dont like this',
            'decision_cinder_id': self.cinder_job.decision.cinder_id,
            'abuse_report_id': None,
            'user_id': user.pk,
            'is_reporter': False,
        }

    def test_appeal_rejection_author_no_cinderjob(self):
        user = user_factory()
        self.addon.authors.add(user)
        self.client.force_login(user)
        decision = ContentDecision.objects.create(
            addon=self.addon,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            cinder_id='some-decision-id',
            action_date=datetime.now(),
        )
        author_appeal_url = reverse(
            'abuse.appeal_author', kwargs={'decision_cinder_id': decision.cinder_id}
        )
        response = self.client.get(author_appeal_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#id_email')
        assert not doc('#appeal-thank-you')
        assert doc('#id_reason')
        assert doc('#appeal-submit')

        response = self.client.post(
            author_appeal_url,
            {'email': 'me@example.com', 'reason': 'I dont like this'},
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#appeal-thank-you')
        assert not doc('#id_reason')
        assert not doc('#appeal-submit')
        assert self.appeal_mock.delay.call_count == 1
        assert self.appeal_mock.delay.call_args_list[0][0] == ()
        assert self.appeal_mock.delay.call_args_list[0][1] == {
            'appeal_text': 'I dont like this',
            'decision_cinder_id': decision.cinder_id,
            'abuse_report_id': None,
            'user_id': user.pk,
            'is_reporter': False,
        }

    def test_appeal_banned_user(self):
        target = user_factory()
        self.cinder_job.decision.update(
            action=DECISION_ACTIONS.AMO_BAN_USER, addon=None, user=target
        )
        self.abuse_report.update(guid=None, user=target)
        response = self.client.post(self.author_appeal_url, {'email': target.email})
        assert response.status_code == 200
        doc = pq(response.content)
        email_input = doc('#id_email')[0]
        assert email_input.type == 'hidden'
        assert doc('#id_reason')
        assert not doc('#appeal-thank-you')
        assert doc('#appeal-submit')
        assert self.appeal_mock.call_count == 0

        response = self.client.post(
            self.author_appeal_url,
            {'email': target.email, 'reason': 'I am not a bad guy'},
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#appeal-thank-you')
        assert not doc('#id_reason')
        assert not doc('#appeal-submit')
        assert self.appeal_mock.delay.call_count == 1
        assert self.appeal_mock.delay.call_args_list[0][0] == ()
        assert self.appeal_mock.delay.call_args_list[0][1] == {
            'appeal_text': 'I am not a bad guy',
            'decision_cinder_id': self.cinder_job.decision.cinder_id,
            'abuse_report_id': None,
            'user_id': None,
            'is_reporter': False,
        }

    def test_appeal_banned_user_wrong_email(self):
        target = user_factory()
        self.cinder_job.decision.update(
            action=DECISION_ACTIONS.AMO_BAN_USER, addon=None, user=target
        )
        self.abuse_report.update(guid=None, user=target)
        response = self.client.post(self.author_appeal_url, {'email': 'me@example.com'})
        assert response.status_code == 200
        doc = pq(response.content)
        email_input = doc('#id_email')[0]
        assert email_input.type == 'email'
        assert doc('ul.errorlist').text() == 'Invalid email provided.'
        assert not doc('#id_reason')
        assert not doc('#appeal-thank-you')
        assert doc('#appeal-submit')
        assert self.appeal_mock.call_count == 0

        response = self.client.post(
            self.author_appeal_url,
            {'email': 'me@example.com', 'reason': 'I am a bad guy'},
        )
        assert response.status_code == 200
        doc = pq(response.content)
        email_input = doc('#id_email')[0]
        assert email_input.type == 'email'
        assert doc('ul.errorlist').text() == 'Invalid email provided.'
        assert not doc('#id_reason')
        assert not doc('#appeal-thank-you')
        assert doc('#appeal-submit')
        assert self.appeal_mock.call_count == 0

    def test_reporter_cant_appeal_appealed_decision_already_made_for_other_affirm(self):
        # 2 reports against the same add-on, initial decision was to approve,
        # first reporter appealed. Second reporter gets to appeal too...
        user = user_factory()
        self.abuse_report.update(reporter=user)
        other_abuse_report = AbuseReport.objects.create(
            reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE,
            guid=self.addon.guid,
            created=self.cinder_job.created,
            cinder_job=self.cinder_job,
            reporter_email='otherreporter@example.com',
        )
        appeal_job = CinderJob.objects.create(job_id='appeal job id')
        self.cinder_job.decision.update(appeal_job=appeal_job)
        CinderAppeal.objects.create(
            decision=self.cinder_job.decision, reporter_report=other_abuse_report
        )

        self.client.force_login(user)
        response = self.client.get(self.reporter_appeal_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#id_reason')
        assert not doc('#appeal-thank-you')
        assert doc('#appeal-submit')

        # ... But if the first appeal already had a decision, then the second
        # reporter can't submit an appeal anymore, it's too late. They get a
        # specific error message (in this case we confirmed the original
        # decision).
        ContentDecision.objects.create(
            cinder_id='appeal decision id',
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=self.addon,
            cinder_job=appeal_job,
        )

        response = self.client.get(self.reporter_appeal_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#id_reason')
        assert not doc('#appeal-thank-you')
        assert not doc('#appeal-submit')
        assert "This decision can't be appealed" not in doc.text()
        assert (
            'We have already reviewed a similar appeal from another reporter, '
            'and affirmed the previous decision' in doc.text()
        )

    def test_reporter_cant_appeal_appealed_decision_already_made_for_other_turned(self):
        # 2 reports against the same add-on, initial decision was to approve,
        # first reporter appealed. Second reporter gets to appeal too...
        user = user_factory()
        self.abuse_report.update(reporter=user)
        other_abuse_report = AbuseReport.objects.create(
            reason=AbuseReport.REASONS.HATEFUL_VIOLENT_DECEPTIVE,
            guid=self.addon.guid,
            created=self.cinder_job.created,
            cinder_job=self.cinder_job,
            reporter_email='otherreporter@example.com',
        )
        appeal_job = CinderJob.objects.create(job_id='appeal job id')
        self.cinder_job.decision.update(appeal_job=appeal_job)
        CinderAppeal.objects.create(
            decision=self.cinder_job.decision, reporter_report=other_abuse_report
        )

        self.client.force_login(user)
        response = self.client.get(self.reporter_appeal_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#id_reason')
        assert not doc('#appeal-thank-you')
        assert doc('#appeal-submit')

        # ... But if the first appeal already had a decision, then the second
        # reporter can't submit an appeal anymore, it's too late. They get a
        # specific error message (in this case the decision was overturned,
        # the content is already supposed to be disabled but the reporter might
        # not have noticed).
        ContentDecision.objects.create(
            cinder_id='appeal decision id',
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=self.addon,
            cinder_job=appeal_job,
        )

        response = self.client.get(self.reporter_appeal_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#id_reason')
        assert not doc('#appeal-thank-you')
        assert not doc('#appeal-submit')
        assert "This decision can't be appealed" not in doc.text()
        assert (
            'We have already reviewed a similar appeal from another reporter, '
            'and have reversed our prior decision'
        ) in doc.text()

    def test_reporter_cant_appeal_overridden_decision(self):
        user = user_factory()
        self.abuse_report.update(reporter=user)

        self.client.force_login(user)
        response = self.client.get(self.reporter_appeal_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#id_reason')
        assert not doc('#appeal-thank-you')
        assert doc('#appeal-submit')

        ContentDecision.objects.create(
            cinder_id='appeal decision id',
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=self.addon,
            override_of=self.cinder_job.decision,
        )

        response = self.client.get(self.reporter_appeal_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#id_reason')
        assert not doc('#appeal-thank-you')
        assert not doc('#appeal-submit')
        assert (
            'The decision you are appealing has already been overridden by a new '
            'decision' in doc.text()
        )

    def test_author_cant_appeal_overridden_decision(self):
        self.cinder_job.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        user = user_factory()
        self.addon.authors.add(user)
        self.client.force_login(user)
        response = self.client.get(self.author_appeal_url)

        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#id_reason')
        assert not doc('#appeal-thank-you')
        assert doc('#appeal-submit')

        ContentDecision.objects.create(
            cinder_id='appeal decision id',
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=self.addon,
            override_of=self.cinder_job.decision,
        )

        response = self.client.get(self.author_appeal_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#id_reason')
        assert not doc('#appeal-thank-you')
        assert not doc('#appeal-submit')
        assert (
            'The decision you are appealing has already been overridden by a new '
            'decision' in doc.text()
        )

    def test_throttling_initial_email_form(self):
        expected_error_message = (
            'You have submitted this form too many times recently. '
            'Please try again after some time.'
        )
        target = user_factory()
        self.cinder_job.decision.update(
            action=DECISION_ACTIONS.AMO_BAN_USER, addon=None, user=target
        )
        self.abuse_report.update(guid=None, user=target)
        with time_machine.travel(datetime.now(), tick=False) as frozen_time:
            for _x in range(0, 20):
                self._add_fake_throttling_action(
                    view_class=AbuseAppealEmailForm,
                    view_kwargs={'expected_email': 'doesntmatter@example.com'},
                    url=self.author_appeal_url,
                    remote_addr='5.6.7.8',
                )
            response = self.client.post(
                self.author_appeal_url,
                {'email': target.email},
                REMOTE_ADDR='5.6.7.8',
            )
            assert (
                expected_error_message
                in response.context_data['appeal_email_form'].non_field_errors()
            )
            doc = pq(response.content)
            assert doc('ul.errorlist').text() == expected_error_message

            # Advance 23 hours, still blocked for that IP.
            frozen_time.shift(delta=timedelta(hours=21))
            assert (
                expected_error_message
                in response.context_data['appeal_email_form'].non_field_errors()
            )
            doc = pq(response.content)
            assert doc('ul.errorlist').text() == expected_error_message

            # Advance one day to be able to submit again with the same IP.
            frozen_time.shift(delta=timedelta(hours=24, seconds=1))
            response = self.client.post(
                self.author_appeal_url,
                {'email': target.email},
                REMOTE_ADDR='5.6.7.8',
            )
            assert (
                expected_error_message
                not in response.context_data['appeal_email_form'].non_field_errors()
            )
            doc = pq(response.content)
            assert doc('#id_reason')
            assert not doc('#appeal-thank-you')
            assert doc('#appeal-submit')

    def test_throttling_doesnt_reveal_validation_state_fields(self):
        expected_error_message = (
            'You have submitted this form too many times recently. '
            'Please try again after some time.'
        )
        target = user_factory()
        self.cinder_job.decision.update(
            action=DECISION_ACTIONS.AMO_BAN_USER, addon=None, user=target
        )
        self.abuse_report.update(guid=None, user=target)
        with time_machine.travel(datetime.now(), tick=False):
            for _x in range(0, 20):
                self._add_fake_throttling_action(
                    view_class=AbuseAppealEmailForm,
                    view_kwargs={'expected_email': 'doesntmatter@example.com'},
                    url=self.author_appeal_url,
                    remote_addr='5.6.7.8',
                )
            response = self.client.post(
                self.author_appeal_url,
                # Email won't be validated because throttling will fail first.
                {'email': 'garbage@example.com'},
                REMOTE_ADDR='5.6.7.8',
            )
            assert (
                expected_error_message
                in response.context_data['appeal_email_form'].non_field_errors()
            )
            assert 'email' not in response.context_data['appeal_email_form'].errors
            doc = pq(response.content)
            assert doc('ul.errorlist').text() == expected_error_message

    def test_throttling_appeal_form(self):
        expected_error_message = (
            'You have submitted this form too many times recently. '
            'Please try again after some time.'
        )
        self.cinder_job.decision.update(action=DECISION_ACTIONS.AMO_DISABLE_ADDON)
        user = user_factory()
        self.addon.authors.add(user)
        self.client.force_login(user)
        with time_machine.travel(datetime.now(), tick=False) as frozen_time:
            for _x in range(0, 20):
                self._add_fake_throttling_action(
                    view_class=AbuseAppealForm,
                    url=self.author_appeal_url,
                    remote_addr='5.6.7.8',
                    user=user,
                )
            response = self.client.post(
                self.author_appeal_url,
                {'reason': 'I dont like this'},
                REMOTE_ADDR='5.6.7.8',
            )
            assert (
                expected_error_message
                in response.context_data['appeal_form'].non_field_errors()
            )
            doc = pq(response.content)
            assert doc('ul.errorlist').text() == expected_error_message
            assert not doc('#appeal-thank-you')

            # Advance 23 hours, still blocked for that IP.
            frozen_time.shift(delta=timedelta(hours=23))
            assert (
                expected_error_message
                in response.context_data['appeal_form'].non_field_errors()
            )
            doc = pq(response.content)
            assert doc('ul.errorlist').text() == expected_error_message
            assert not doc('#appeal-thank-you')

            # Advance one day to be able to submit again with the same IP.
            frozen_time.shift(delta=timedelta(hours=24, seconds=1))
            response = self.client.post(
                self.author_appeal_url,
                {'reason': 'I dont like this'},
                REMOTE_ADDR='5.6.7.8',
            )
            assert (
                expected_error_message
                not in response.context_data['appeal_form'].non_field_errors()
            )
            doc = pq(response.content)
            assert doc('#appeal-thank-you')
