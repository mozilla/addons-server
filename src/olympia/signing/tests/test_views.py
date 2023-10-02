import json
import os
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.forms import ValidationError
from django.test.testcases import TransactionTestCase
from django.test.utils import override_settings
from django.utils import translation

import responses
from freezegun import freeze_time
from rest_framework.response import Response

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonUser
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    create_default_webext_appversion,
    developer_factory,
    get_random_ip,
    reverse_ns,
)
from olympia.api.tests.utils import APIKeyAuthTestMixin
from olympia.files.models import File, FileUpload
from olympia.files.utils import get_sha256
from olympia.users.models import (
    EmailUserRestriction,
    IPNetworkUserRestriction,
    UserProfile,
    UserRestrictionHistory,
)
from olympia.versions.models import Version

from ..views import VersionView


class SigningAPITestMixin(APIKeyAuthTestMixin):
    def setUp(self):
        self.user = developer_factory(
            email='del@icio.us', read_dev_agreement=datetime.now()
        )
        self.api_key = self.create_api_key(self.user, str(self.user.pk) + ':f')


class BaseUploadVersionTestMixin(SigningAPITestMixin):
    @classmethod
    def setUpTestData(cls):
        create_default_webext_appversion()

    def setUp(self):
        super().setUp()
        self.guid = '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}'
        addon_factory(
            guid=self.guid,
            version_kw={'version': '2.1.072'},
            users=[self.user],
        )

        self.view_class = VersionView

    def url(self, guid, version, pk=None):
        if guid is None:
            args = [version]
        else:
            args = [guid, version]
        if pk is not None:
            args.append(pk)
        return reverse_ns('signing.version', api_version='v4', args=args)

    def create_version(self, version):
        response = self.request('PUT', self.url(self.guid, version), version)
        assert response.status_code in [201, 202]

    def xpi_filepath(self, guid, version):
        return os.path.join(
            'src',
            'olympia',
            'signing',
            'fixtures',
            f'{guid}-{version}.xpi',
        )

    def request(
        self,
        method='PUT',
        url=None,
        version='3.0',
        guid='@upload-version',
        filename=None,
        channel=None,
        extra_kwargs=None,
    ):
        if filename is None:
            filename = self.xpi_filepath(guid, version)
        if url is None:
            url = self.url(guid, version)

        with open(filename, 'rb') as upload:
            data = {'upload': upload}
            if method == 'POST' and version:
                data['version'] = version
            if channel:
                data['channel'] = channel

            return getattr(self.client, method.lower())(
                url,
                data,
                HTTP_AUTHORIZATION=self.authorization(),
                HTTP_USER_AGENT='web-ext/12.34',
                format='multipart',
                **(extra_kwargs or {}),
            )

    def make_admin(self, user):
        admin_group = Group.objects.create(name='Admin', rules='*:*')
        GroupUser.objects.create(group=admin_group, user=user)


class TestUploadVersion(BaseUploadVersionTestMixin, TestCase):
    def test_not_authenticated(self):
        # Use self.client.put so that we don't add the authorization header.
        response = self.client.put(self.url(self.guid, '12.5'))
        assert response.status_code == 401

    def test_addon_does_not_exist(self):
        guid = '@create-version'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        with mock.patch('olympia.addons.utils.statsd.incr') as statsd_incr_mock:
            response = self.request('PUT', guid=guid, version='1.0')
        assert response.status_code == 201
        assert qs.exists()
        addon = qs.get()
        assert addon.guid == guid
        assert addon.has_author(self.user)
        assert addon.status == amo.STATUS_NULL
        latest_version = addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)
        assert latest_version
        assert latest_version.channel == amo.CHANNEL_UNLISTED
        assert (
            ActivityLog.objects.for_addons(addon)
            .filter(action=amo.LOG.CREATE_ADDON.id)
            .count()
            == 1
        )
        statsd_incr_mock.assert_any_call('signing.submission.webext_version.12_34')

    def test_new_addon_random_slug_unlisted_channel(self):
        guid = '@create-webextension'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request('PUT', guid=guid, version='1.0')
        assert response.status_code == 201
        assert qs.exists()
        addon = qs.get()

        assert len(addon.slug) == 20
        assert 'create' not in addon.slug

    def test_user_does_not_own_addon(self):
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now(), email='foo@bar.com'
        )
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 403
        assert response.data['error'] == 'You do not own this add-on.'

    def test_admin_does_not_own_addon(self):
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now(), email='foo@bar.com'
        )
        self.api_key = self.create_api_key(self.user, 'bar')
        self.make_admin(self.user)
        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 403
        assert response.data['error'] == 'You do not own this add-on.'

    def test_version_does_not_match_manifest_file(self):
        response = self.request('PUT', self.url(self.guid, '2.5'))
        assert response.status_code == 400
        assert response.data['error'] == ('Version does not match the manifest file.')

    def test_version_already_exists(self):
        response = self.request(
            'PUT', self.url(self.guid, '2.1.072'), version='2.1.072'
        )
        assert response.status_code == 409
        assert response.data['error'] == ('Version 2.1.072 already exists.')

    @mock.patch('olympia.devhub.views.Version.from_upload')
    def test_no_version_yet(self, from_upload):
        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 202
        assert 'processed' in response.data

        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

    def test_version_added(self):
        assert Addon.objects.get(guid=self.guid).status == amo.STATUS_APPROVED
        qs = Version.objects.filter(addon__guid=self.guid, version='3.0')
        assert not qs.exists()
        existing = Version.objects.filter(addon__guid=self.guid)
        assert existing.count() == 1
        assert existing[0].channel == amo.CHANNEL_LISTED

        with mock.patch('olympia.addons.utils.statsd.incr') as statsd_incr_mock:
            response = self.request(
                'PUT',
                self.url(self.guid, '3.0'),
                extra_kwargs={'REMOTE_ADDR': '127.0.2.1'},
            )
        assert response.status_code == 202
        assert 'processed' in response.data

        upload = FileUpload.objects.latest('pk')
        assert upload.source == amo.UPLOAD_SOURCE_SIGNING_API
        assert upload.user == self.user
        assert upload.ip_address == '127.0.2.1'

        version = qs.get()
        assert version.addon.guid == self.guid
        assert version.version == '3.0'
        assert version.file.status == amo.STATUS_AWAITING_REVIEW
        assert version.addon.status == amo.STATUS_APPROVED
        assert version.channel == amo.CHANNEL_LISTED
        assert not version.file.is_mozilla_signed_extension

        statsd_incr_mock.assert_any_call('signing.submission.webext_version.12_34')

    def test_version_already_uploaded(self):
        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 202
        assert 'processed' in response.data

        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 409
        assert response.data['error'] == ('Version 3.0 already exists.')

    def test_only_version_already_uploaded_was_deleted(self):
        # Make the only version conflict with the version number we're about to
        # upload, and soft-delete it.
        Version.objects.filter(addon__guid=self.guid, version='2.1.072').update(
            version='3.0', deleted=True
        )
        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 409, response.data
        assert response.data['error'] == (
            'Version 3.0 was uploaded before and deleted.'
        )

    def test_version_failed_review(self):
        self.create_version('3.0')
        version = Version.objects.get(addon__guid=self.guid, version='3.0')
        version.update(human_review_date=datetime.today())
        version.file.update(status=amo.STATUS_DISABLED)

        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 409
        assert response.data['error'] == ('Version 3.0 already exists.')

        # Verify that you can check the status after upload (#953).
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

    def test_version_num_must_be_greater(self):
        version = Version.objects.filter(addon__guid=self.guid, version='2.1.072')[0]
        version.update(version='3.1')
        version.file.update(is_signed=True)

        response = self.request('PUT', self.url(self.guid, '3.0'), channel='listed')
        assert response.status_code == 409
        assert response.data['error'] == (
            'Version 3.0 must be greater than the previous approved version 3.1.'
        )

    def test_version_num_must_be_numerically_greater(self):
        version = Version.objects.filter(addon__guid=self.guid, version='2.1.072')[0]
        version.update(version='3.0.0')
        version.file.update(is_signed=True)

        response = self.request('PUT', self.url(self.guid, '3.0'), channel='listed')
        assert response.status_code == 409
        assert response.data['error'] == (
            'Version 3.0 must be greater than the previous approved version 3.0.0.'
        )

    def test_version_added_is_experiment(self):
        self.grant_permission(self.user, 'Experiments:submit')
        guid = '@experiment-inside-webextension-guid'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request(
            'PUT',
            guid=guid,
            version='0.0.1',
            # Note: this extension is NOT signed but it contains a
            # `META-INF/manifest.mf` file to force addons-linter to NOT emit
            # errors related to this extension being privileged. This allows
            # the test case to continue to work as expected.
            filename='src/olympia/files/fixtures/files/'
            'experiment_inside_webextension.xpi',
        )
        assert response.status_code == 201
        assert qs.exists()
        addon = qs.get()
        assert addon.has_author(self.user)
        assert addon.status == amo.STATUS_NULL
        latest_version = addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)
        assert latest_version
        assert latest_version.channel == amo.CHANNEL_UNLISTED

    def test_version_added_is_experiment_reject_no_perm(self):
        guid = '@experiment-inside-webextension-guid'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request(
            'PUT',
            guid=guid,
            version='0.1',
            filename='src/olympia/files/fixtures/files/'
            'experiment_inside_webextension.xpi',
        )
        assert response.status_code == 400
        assert response.data['error'] == ('You cannot submit this type of add-on')

    def test_mozilla_signed_allowed(self):
        guid = '@webextension-guid'
        self.grant_permission(self.user, 'SystemAddon:Submit')
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request(
            'PUT',
            guid=guid,
            version='0.0.1',
            filename='src/olympia/files/fixtures/files/'
            'webextension_signed_already.xpi',
        )
        assert response.status_code == 201
        assert qs.exists()
        addon = qs.get()
        assert addon.has_author(self.user)
        assert addon.status == amo.STATUS_NULL
        latest_version = addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)
        assert latest_version
        assert latest_version.channel == amo.CHANNEL_UNLISTED
        assert latest_version.file.is_mozilla_signed_extension

    def test_mozilla_signed_not_allowed(self):
        guid = '@webextension-guid'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request(
            'PUT',
            guid=guid,
            version='0.0.1',
            filename='src/olympia/files/fixtures/files/'
            'webextension_signed_already.xpi',
        )
        assert response.status_code == 400
        assert response.data['error'] == (
            'You cannot submit a Mozilla Signed Extension'
        )

    def test_restricted_guid_addon_allowed(self):
        guid = 'systemaddon@mozilla.org'
        self.grant_permission(self.user, 'SystemAddon:Submit')
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request(
            'PUT',
            guid=guid,
            version='0.0.1',
            filename='src/olympia/files/fixtures/files/mozilla_guid.xpi',
        )
        assert response.status_code == 201
        assert qs.exists()
        addon = qs.get()
        assert addon.has_author(self.user)
        assert addon.status == amo.STATUS_NULL
        latest_version = addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)
        assert latest_version
        assert latest_version.channel == amo.CHANNEL_UNLISTED

    def test_restricted_guid_addon_not_allowed(self):
        guid = 'systemaddon@mozilla.com'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request(
            'PUT',
            guid=guid,
            version='0.1',
            filename='src/olympia/files/fixtures/files/mozilla_guid.xpi',
        )
        assert response.status_code == 400
        assert response.data['error'] == (
            'You cannot submit an add-on using an ID ending with this suffix'
        )

    def test_restricted_guid_addon_update_allowed(self):
        """Updates to restricted IDs are allowed from anyone."""
        guid = 'systemaddon@mozilla.org'
        self.user.update(email='pinkpanda@notzilla.com')
        orig_addon = addon_factory(
            guid='systemaddon@mozilla.org',
            version_kw={'channel': amo.CHANNEL_UNLISTED},
        )
        AddonUser.objects.create(addon=orig_addon, user=self.user)
        response = self.request(
            'PUT',
            guid=guid,
            version='0.0.1',
            filename='src/olympia/files/fixtures/files/mozilla_guid.xpi',
        )
        assert response.status_code == 202
        addon = Addon.unfiltered.filter(guid=guid).get()
        assert addon.versions.count() == 2
        latest_version = addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)
        assert latest_version
        assert latest_version.channel == amo.CHANNEL_UNLISTED

    def test_invalid_version_response_code(self):
        # This raises an error in parse_addon which is not covered by
        # an exception handler.
        response = self.request(
            'PUT',
            self.url(self.guid, '1.0'),
            guid='@create-webextension-invalid-version',
            version='1.0',
        )
        assert response.status_code == 400

    def test_raises_response_code(self):
        # A check that any bare error in handle_upload will return a 400.
        with mock.patch('olympia.signing.views.devhub_handle_upload') as patch:
            patch.side_effect = ValidationError(message='some error')
            response = self.request('PUT', self.url(self.guid, '1.0'))
            assert response.status_code == 400

    def test_no_version_upload_for_admin_disabled_addon(self):
        addon = Addon.objects.get(guid=self.guid)
        addon.update(status=amo.STATUS_DISABLED)

        response = self.request('PUT', self.url(self.guid, '3.0'), version='3.0')
        assert response.status_code == 400
        error_msg = 'cannot add versions to an add-on that has status: %s.' % (
            amo.STATUS_CHOICES_ADDON[amo.STATUS_DISABLED]
        )
        assert error_msg in response.data['error']

    def test_no_listed_version_upload_for_user_disabled_addon(self):
        addon = Addon.objects.get(guid=self.guid)
        addon.update(disabled_by_user=True)
        assert not addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)

        response = self.request('PUT', self.url(self.guid, '3.0'), version='3.0')
        assert response.status_code == 400
        error_msg = 'cannot add listed versions to an add-on set to "Invisible"'
        assert error_msg in response.data['error']

        response = self.request(
            'PUT', self.url(self.guid, '3.0'), version='3.0', channel='listed'
        )
        assert response.status_code == 400
        assert error_msg in response.data['error']

        response = self.request(
            'PUT', self.url(self.guid, '3.0'), version='3.0', channel='unlisted'
        )
        assert response.status_code == 202
        assert addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)

    def test_channel_ignored_for_new_addon(self):
        guid = '@create-version'
        qs = Addon.unfiltered.filter(guid=guid)
        assert not qs.exists()
        response = self.request('PUT', guid=guid, version='1.0', channel='listed')
        assert response.status_code == 201
        addon = qs.get()
        assert addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)

    def test_no_channel_selects_last_channel(self):
        addon = Addon.objects.get(guid=self.guid)
        assert addon.status == amo.STATUS_APPROVED
        assert addon.versions.count() == 1
        assert addon.versions.all()[0].channel == amo.CHANNEL_LISTED

        response = self.request('PUT', self.url(self.guid, '3.0'))
        assert response.status_code == 202, response.data['error']
        assert 'processed' in response.data
        new_version = addon.versions.latest()
        assert new_version.channel == amo.CHANNEL_LISTED

        new_version.update(channel=amo.CHANNEL_UNLISTED)

        response = self.request(
            'PUT', self.url(self.guid, '4.0-beta1'), version='4.0-beta1'
        )
        assert response.status_code == 202, response.data['error']
        assert 'processed' in response.data
        third_version = addon.versions.latest()
        assert third_version.channel == amo.CHANNEL_UNLISTED

    def test_unlisted_channel_for_listed_addon(self):
        addon = Addon.objects.get(guid=self.guid)
        assert addon.status == amo.STATUS_APPROVED
        assert addon.versions.count() == 1
        assert addon.versions.all()[0].channel == amo.CHANNEL_LISTED

        response = self.request('PUT', self.url(self.guid, '3.0'), channel='unlisted')
        assert response.status_code == 202, response.data['error']
        assert 'processed' in response.data
        assert addon.versions.latest().channel == amo.CHANNEL_UNLISTED

    def test_listed_channel_for_complete_listed_addon(self):
        addon = Addon.objects.get(guid=self.guid)
        assert addon.status == amo.STATUS_APPROVED
        assert addon.versions.count() == 1
        assert addon.has_complete_metadata()

        response = self.request('PUT', self.url(self.guid, '3.0'), channel='listed')
        assert response.status_code == 202, response.data['error']
        assert 'processed' in response.data
        assert addon.versions.latest().channel == amo.CHANNEL_LISTED

    def test_listed_channel_fails_for_incomplete_addon(self):
        addon = Addon.objects.get(guid=self.guid)
        assert addon.status == amo.STATUS_APPROVED
        assert addon.versions.count() == 1
        addon.current_version.update(license=None)  # Make addon incomplete.
        addon.versions.latest().update(channel=amo.CHANNEL_UNLISTED)
        assert not addon.has_complete_metadata(has_listed_versions=True)

        response = self.request('PUT', self.url(self.guid, '3.0'), channel='listed')
        assert response.status_code == 400
        error_msg = 'You cannot add a listed version to this add-on via the API'
        assert error_msg in response.data['error']

    def test_invalid_guid_in_package_post(self):
        Addon.objects.all().delete()

        response = self.request(
            'POST',
            url=reverse_ns('signing.version', api_version='v4'),
            version='1.0',
            filename='src/olympia/files/fixtures/files/invalid_guid.xpi',
        )
        assert response.status_code == 400
        assert response.data == {'error': 'Invalid Add-on ID in URL or package'}
        assert not Addon.unfiltered.filter(guid='this_guid_is_invalid').exists()
        assert not Addon.objects.exists()

    def _test_throttling_verb_ip_burst(self, verb, url, expected_status=201):
        # Bulk-create a bunch of users we'll need to make sure the user is
        # different every time, so that we test IP throttling specifically.
        users = [
            UserProfile(username='bûlk%d' % i, email='bulk%d@example.com' % i)
            for i in range(0, 6)
        ]
        UserProfile.objects.bulk_create(users)
        users = UserProfile.objects.filter(email__startswith='bulk')
        with freeze_time('2019-04-08 15:16:23.42') as frozen_time:
            for user in users:
                self._add_fake_throttling_action(
                    view_class=self.view_class,
                    url=url,
                    user=user,
                    remote_addr='63.245.208.194',
                )

            # At this point we should be throttled since we're using the same
            # IP. (we're still inside the frozen time context).
            response = self.request(
                verb,
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': '63.245.208.194',
                    'HTTP_X_FORWARDED_FOR': f'63.245.208.194, {get_random_ip()}',
                },
            )
            assert response.status_code == 429, response.content

            # 'Burst' throttling is 1 minute, so 61 seconds later we should be
            # allowed again.
            frozen_time.tick(delta=timedelta(seconds=61))
            response = self.request(
                verb,
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': '63.245.208.194',
                    'HTTP_X_FORWARDED_FOR': f'63.245.208.194, {get_random_ip()}',
                },
            )
            assert response.status_code == expected_status

    def _test_throttling_verb_ip_hourly(self, verb, url, expected_status=201):
        # Bulk-create a bunch of users we'll need to make sure the user is
        # different every time, so that we test IP throttling specifically.
        users = [
            UserProfile(username='bûlk%d' % i, email='bulk%d@example.com' % i)
            for i in range(0, 50)
        ]
        UserProfile.objects.bulk_create(users)
        users = UserProfile.objects.filter(email__startswith='bulk')
        with freeze_time('2019-04-08 15:16:23.42') as frozen_time:
            for user in users:
                # Make the user different every time so that we test the ip
                # throttling.
                self._add_fake_throttling_action(
                    view_class=self.view_class,
                    url=url,
                    user=user,
                    remote_addr='63.245.208.194',
                )

            # At this point we should be throttled since we're using the same
            # IP. (we're still inside the frozen time context).
            response = self.request(
                verb,
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': '63.245.208.194',
                    'HTTP_X_FORWARDED_FOR': f'63.245.208.194, {get_random_ip()}',
                },
            )
            assert response.status_code == 429

            # One minute later, past the 'burst' throttling period, we're still
            # blocked by the 'hourly' limit.
            frozen_time.tick(delta=timedelta(seconds=61))
            response = self.request(
                verb,
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': '63.245.208.194',
                    'HTTP_X_FORWARDED_FOR': f'63.245.208.194, {get_random_ip()}',
                },
            )
            assert response.status_code == 429

            # 'hourly' throttling is 1 hour, so 3601 seconds later we should
            # be allowed again.
            frozen_time.tick(delta=timedelta(seconds=3601))
            response = self.request(
                verb,
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': '63.245.208.194',
                    'HTTP_X_FORWARDED_FOR': f'63.245.208.194, {get_random_ip()}',
                },
            )
            assert response.status_code == expected_status

    def _test_throttling_verb_user_burst(self, verb, url, expected_status=201):
        with freeze_time('2019-04-08 15:16:23.42') as frozen_time:
            for _x in range(0, 6):
                # Make the IP different every time so that we test the user
                # throttling.
                self._add_fake_throttling_action(
                    view_class=self.view_class,
                    url=url,
                    user=self.user,
                    remote_addr=get_random_ip(),
                )

            # At this point we should be throttled since we're using the same
            # user. (we're still inside the frozen time context).
            response = self.request(
                verb,
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': get_random_ip(),
                    'HTTP_X_FORWARDED_FOR': f'{get_random_ip()}, {get_random_ip()}',
                },
            )
            assert response.status_code == 429

            # 'Burst' throttling is 1 minute, so 61 seconds later we should be
            # allowed again.
            frozen_time.tick(delta=timedelta(seconds=61))
            response = self.request(
                verb,
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': get_random_ip(),
                    'HTTP_X_FORWARDED_FOR': f'{get_random_ip()}, {get_random_ip()}',
                },
            )
            assert response.status_code == expected_status

    def _test_throttling_verb_user_hourly(self, verb, url, expected_status=201):
        with freeze_time('2019-04-08 15:16:23.42') as frozen_time:
            # 21 is above the hourly limit but below the daily one.
            for _x in range(0, 21):
                # Make the IP different every time so that we test the user
                # throttling.
                self._add_fake_throttling_action(
                    view_class=self.view_class,
                    url=url,
                    user=self.user,
                    remote_addr=get_random_ip(),
                )

            # At this point we should be throttled since we're using the same
            # user. (we're still inside the frozen time context).
            response = self.request(
                verb,
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': get_random_ip(),
                    'HTTP_X_FORWARDED_FOR': f'{get_random_ip()}, {get_random_ip()}',
                },
            )
            assert response.status_code == 429

            # One minute later, past the 'burst' throttling period, we're still
            # blocked by the 'hourly' limit.
            frozen_time.tick(delta=timedelta(seconds=61))
            response = self.request(
                verb,
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': get_random_ip(),
                    'HTTP_X_FORWARDED_FOR': f'{get_random_ip()}, {get_random_ip()}',
                },
            )
            assert response.status_code == 429

            # 3601 seconds later we should be allowed again.
            frozen_time.tick(delta=timedelta(seconds=3601))
            response = self.request(
                verb,
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': get_random_ip(),
                    'HTTP_X_FORWARDED_FOR': f'{get_random_ip()}, {get_random_ip()}',
                },
            )
            assert response.status_code == expected_status, response.json()

    def _test_throttling_verb_user_daily(self, verb, url, expected_status=201):
        with freeze_time('2019-04-08 15:16:23.42') as frozen_time:
            for _x in range(0, 50):
                # Make the IP different every time so that we test the user
                # throttling.
                self._add_fake_throttling_action(
                    view_class=self.view_class,
                    url=url,
                    user=self.user,
                    remote_addr=get_random_ip(),
                )

            # At this point we should be throttled since we're using the same
            # user. (we're still inside the frozen time context).
            response = self.request(
                verb,
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': get_random_ip(),
                    'HTTP_X_FORWARDED_FOR': f'{get_random_ip()}, {get_random_ip()}',
                },
            )
            assert response.status_code == 429

            # One minute later, past the 'burst' throttling period, we're still
            # blocked by the 'hourly' limit.
            frozen_time.tick(delta=timedelta(seconds=61))
            response = self.request(
                verb,
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': get_random_ip(),
                    'HTTP_X_FORWARDED_FOR': f'{get_random_ip()}, {get_random_ip()}',
                },
            )
            assert response.status_code == 429

            # After the hourly limit, still blocked.
            frozen_time.tick(delta=timedelta(seconds=3601))
            response = self.request(
                verb,
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': get_random_ip(),
                    'HTTP_X_FORWARDED_FOR': f'{get_random_ip()}, {get_random_ip()}',
                },
            )
            assert response.status_code == 429

            # 86401 seconds later we should be allowed again (24h + 1s).
            frozen_time.tick(delta=timedelta(seconds=86401))
            response = self.request(
                verb,
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': get_random_ip(),
                    'HTTP_X_FORWARDED_FOR': f'{get_random_ip()}, {get_random_ip()}',
                },
            )
            assert response.status_code == expected_status

    def test_throttling_post_ip_burst(self):
        url = reverse_ns('signing.version', api_version='v4')
        self._test_throttling_verb_ip_burst('POST', url)

    def test_throttling_post_ip_hourly(self):
        url = reverse_ns('signing.version', api_version='v4')
        self._test_throttling_verb_ip_hourly('POST', url)

    def test_throttling_post_user_burst(self):
        url = reverse_ns('signing.version', api_version='v4')
        self._test_throttling_verb_user_burst('POST', url)

    def test_throttling_post_user_hourly(self):
        url = reverse_ns('signing.version', api_version='v4')
        self._test_throttling_verb_user_hourly('POST', url)

    def test_throttling_post_user_daily(self):
        url = reverse_ns('signing.version', api_version='v4')
        self._test_throttling_verb_user_daily('POST', url)

    def test_throttling_put_ip_burst(self):
        url = self.url(self.guid, '3.0')
        self._test_throttling_verb_ip_burst('PUT', url, expected_status=202)

    def test_throttling_put_ip_hourly(self):
        url = self.url(self.guid, '3.0')
        self._test_throttling_verb_ip_hourly('PUT', url, expected_status=202)

    def test_throttling_put_user_burst(self):
        url = self.url(self.guid, '3.0')
        self._test_throttling_verb_user_burst('PUT', url, expected_status=202)

    def test_throttling_put_user_hourly(self):
        url = self.url(self.guid, '3.0')
        self._test_throttling_verb_user_hourly('PUT', url, expected_status=202)

    def test_throttling_put_user_daily(self):
        url = self.url(self.guid, '3.0')
        self._test_throttling_verb_user_daily('PUT', url, expected_status=202)

    def test_throttling_ignored_for_special_users(self):
        self.grant_permission(
            self.user, ':'.join(amo.permissions.API_BYPASS_THROTTLING)
        )
        url = self.url(self.guid, '3.0')
        with freeze_time('2019-04-08 15:16:23.42'):
            for _x in range(0, 60):
                # With that many actions all throttling classes should prevent
                # the user from submitting an addon...
                self._add_fake_throttling_action(
                    view_class=self.view_class,
                    url=url,
                    user=self.user,
                    remote_addr='1.2.3.4',
                )

            # ... But it works, because it's a special user allowed to bypass
            # throttling.
            response = self.request(
                'PUT',
                url=url,
                guid='@create-webextension',
                extra_kwargs={
                    'REMOTE_ADDR': '1.2.3.4',
                    'HTTP_X_FORWARDED_FOR': f'1.2.3.4, {get_random_ip()}',
                },
            )
            assert response.status_code == 202

    def test_deleted_webextension(self):
        guid = '@webextension-with-guid'
        addon = addon_factory(guid=guid, users=[self.user])
        addon.delete()
        response = self.request(
            'POST',
            guid=guid,
            version='1.0',
            filename=self.xpi_filepath('@create-webextension-with-guid', '1.0'),
            url=reverse_ns('signing.version', api_version='v4'),
        )
        assert response.status_code == 400
        assert response.data['error'] == 'Duplicate add-on ID found.'


class TestUploadVersionWebextension(BaseUploadVersionTestMixin, TestCase):
    def test_addon_does_not_exist_webextension(self):
        response = self.request(
            'POST',
            url=reverse_ns('signing.version', api_version='v4'),
            guid='@create-webextension',
            version='1.0',
            extra_kwargs={'REMOTE_ADDR': '127.0.3.1'},
        )
        assert response.status_code == 201

        guid = response.data['guid']
        addon = Addon.unfiltered.get(guid=guid)

        assert addon.guid is not None
        assert addon.guid != self.guid

        upload = FileUpload.objects.latest('pk')
        assert upload.version == '1.0'
        assert upload.user == self.user
        assert upload.source == amo.UPLOAD_SOURCE_SIGNING_API
        assert upload.ip_address == '127.0.3.1'

        assert addon.has_author(self.user)
        assert addon.status == amo.STATUS_NULL
        latest_version = addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)
        assert latest_version
        assert latest_version.channel == amo.CHANNEL_UNLISTED

    def test_post_addon_restricted(self):
        Addon.objects.all().get().delete()
        assert Addon.objects.count() == 0
        EmailUserRestriction.objects.create(email_pattern=self.user.email)
        response = self.request(
            'POST',
            url=reverse_ns('signing.version', api_version='v4'),
            guid='@create-webextension',
            version='1.0',
        )
        assert response.status_code == 403
        assert json.loads(response.content.decode('utf-8')) == {
            'detail': 'The email address used for your account is not '
            'allowed for submissions.'
        }
        EmailUserRestriction.objects.all().delete()
        IPNetworkUserRestriction.objects.create(network='127.0.0.1/32')
        response = self.request(
            'POST',
            url=reverse_ns('signing.version', api_version='v4'),
            guid='@create-webextension',
            version='1.0',
        )
        assert response.status_code == 403
        assert json.loads(response.content.decode('utf-8')) == {
            'detail': 'Multiple submissions violating our policies have been sent from '
            'your location. The IP address has been blocked.'
        }
        assert Addon.objects.count() == 0

    @override_settings(
        REPUTATION_SERVICE_URL='https://reputation.example.com',
        REPUTATION_SERVICE_TOKEN='atoken',
    )
    def test_post_addon_restricted_by_reputation_ip(self):
        Addon.objects.all().get().delete()
        assert Addon.objects.count() == 0
        responses.add(
            responses.GET,
            'https://reputation.example.com/type/ip/127.0.0.1',
            content_type='application/json',
            json={'reputation': 45},
        )
        responses.add(
            responses.GET,
            'https://reputation.example.com/type/email/%s' % self.user.email,
            content_type='application/json',
            status=404,
        )
        response = self.request(
            'POST',
            url=reverse_ns('signing.version', api_version='v4'),
            guid='@create-webextension',
            version='1.0',
        )
        assert response.status_code == 403
        assert json.loads(response.content.decode('utf-8')) == {
            'detail': 'Multiple submissions violating our policies have been sent from '
            'your location. The IP address has been blocked.'
        }
        assert len(responses.calls) == 2
        assert Addon.objects.count() == 0

    @override_settings(
        REPUTATION_SERVICE_URL='https://reputation.example.com',
        REPUTATION_SERVICE_TOKEN='some_token',
    )
    def test_post_addon_restricted_by_reputation_email(self):
        Addon.objects.all().get().delete()
        assert Addon.objects.count() == 0
        responses.add(
            responses.GET,
            'https://reputation.example.com/type/ip/127.0.0.1',
            content_type='application/json',
            status=404,
        )
        responses.add(
            responses.GET,
            'https://reputation.example.com/type/email/%s' % self.user.email,
            content_type='application/json',
            json={'reputation': 45},
        )
        response = self.request(
            'POST',
            url=reverse_ns('signing.version', api_version='v4'),
            guid='@create-webextension',
            version='1.0',
        )
        assert response.status_code == 403
        assert json.loads(response.content.decode('utf-8')) == {
            'detail': 'The email address used for your account is not '
            'allowed for submissions.'
        }
        assert len(responses.calls) == 2
        assert Addon.objects.count() == 0

    def test_addon_does_not_exist_webextension_with_guid_in_url(self):
        guid = '@custom-guid-provided'
        # Override the filename self.request() picks, we want that specific
        # file but with a custom guid.
        filename = self.xpi_filepath('@create-webextension', '1.0')
        response = self.request(
            'PUT',  # PUT, not POST, since we're specifying a guid in the URL.
            filename=filename,
            guid=guid,  # Will end up in the url since we're not passing one.
            version='1.0',
        )
        assert response.status_code == 201

        assert response.data['guid'] == '@custom-guid-provided'
        addon = Addon.unfiltered.get(guid=response.data['guid'])
        assert addon.guid == '@custom-guid-provided'

        assert addon.has_author(self.user)
        assert addon.status == amo.STATUS_NULL
        latest_version = addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)
        assert latest_version
        assert latest_version.channel == amo.CHANNEL_UNLISTED

    def test_addon_does_not_exist_webextension_with_invalid_guid_in_url(self):
        guid = 'custom-invalid-guid-provided'
        # Override the filename self.request() picks, we want that specific
        # file but with a custom guid.
        filename = self.xpi_filepath('@create-webextension', '1.0')
        response = self.request(
            'PUT',  # PUT, not POST, since we're specifying a guid in the URL.
            filename=filename,
            guid=guid,  # Will end up in the url since we're not passing one.
            version='1.0',
        )
        assert response.status_code == 400
        assert response.data['error'] == 'Invalid Add-on ID in URL or package'
        assert not Addon.unfiltered.filter(guid=guid).exists()

    def test_deleted_webextension(self):
        guid = '@webextension-with-guid'
        addon = addon_factory(guid=guid, users=[self.user])
        addon.delete()
        response = self.request(
            'PUT',
            filename=self.xpi_filepath('@create-webextension-with-guid', '1.0'),
            guid=guid,
            version='1.0',
        )

        assert response.status_code == 400
        assert response.data['error'] == 'Duplicate add-on ID found.'

    def test_webextension_reuse_guid(self):
        response = self.request(
            'POST',
            url=reverse_ns('signing.version', api_version='v4'),
            guid='@create-webextension-with-guid',
            version='1.0',
        )

        guid = response.data['guid']
        assert guid == '@webextension-with-guid'

        addon = Addon.unfiltered.get(guid=guid)
        assert addon.guid == '@webextension-with-guid'

    def test_webextension_reuse_guid_but_only_create(self):
        # Uploading the same version with the same id fails. People
        # have to use the regular `PUT` endpoint for that.
        response = self.request(
            'POST',
            url=reverse_ns('signing.version', api_version='v4'),
            guid='@create-webextension-with-guid',
            version='1.0',
        )
        assert response.status_code == 201

        response = self.request(
            'POST',
            url=reverse_ns('signing.version', api_version='v4'),
            guid='@create-webextension-with-guid',
            version='1.0',
        )
        assert response.status_code == 400
        assert response.data['error'] == 'Duplicate add-on ID found.'

    def test_webextension_optional_version(self):
        # Uploading the same version with the same id fails. People
        # have to use the regular `PUT` endpoint for that.
        response = self.request(
            'POST',
            url=reverse_ns('signing.version', api_version='v4'),
            guid='@create-webextension-with-guid-and-version',
            version='99.0',
        )
        assert response.status_code == 201
        assert response.data['guid'] == '@create-webextension-with-guid-and-version'
        assert response.data['version'] == '99.0'

    def test_webextension_resolve_translations(self):
        fname = 'src/olympia/files/fixtures/files/notify-link-clicks-i18n.xpi'

        response = self.request(
            'POST',
            url=reverse_ns('signing.version', api_version='v4'),
            guid='@notify-link-clicks-i18n',
            version='1.0',
            filename=fname,
        )
        assert response.status_code == 201

        addon = Addon.unfiltered.get(guid=response.data['guid'])

        # Normalized from `en` to `en-US`
        assert addon.default_locale == 'en-US'
        assert addon.name == 'Notify link clicks i18n'
        assert addon.summary == ('Shows a notification when the user clicks on links.')

        translation.activate('de')
        addon.reload()
        assert addon.name == 'Meine Beispielerweiterung'
        assert addon.summary == 'Benachrichtigt den Benutzer über Linkklicks'

    def test_too_long_guid_not_in_manifest_forbidden(self):
        fname = 'src/olympia/files/fixtures/files/webextension_no_id.xpi'

        guid = (
            'this_guid_is_longer_than_the_limit_of_64_chars_see_bug_1201176_'
            'and_should_fail@webextension-guid'
        )

        response = self.request(
            'PUT', url=self.url(guid, '1.0'), version='1.0', filename=fname
        )
        assert response.status_code == 400
        assert response.data == {
            'error': (
                "Please specify your Add-on ID in the manifest if it's "
                'longer than 64 characters.'
            )
        }

        assert not Addon.unfiltered.filter(guid=guid).exists()

    def test_too_long_guid_in_manifest_allowed(self):
        fname = 'src/olympia/files/fixtures/files/webextension_too_long_guid.xpi'

        guid = (
            'this_guid_is_longer_than_the_limit_of_64_chars_see_bug_1201176_'
            'and_should_fail@webextension-guid'
        )

        response = self.request(
            'PUT', url=self.url(guid, '1.0'), version='1.0', filename=fname
        )
        assert response.status_code == 201
        assert Addon.unfiltered.filter(guid=guid).exists()


class TestTestUploadVersionWebextensionTransactions(
    BaseUploadVersionTestMixin, TestCase, TransactionTestCase
):
    # Tests to make sure transactions don't prevent
    # ActivityLog/UserRestrictionHistory objects to be saved.

    def test_activity_log_saved_on_throttling(self):
        url = reverse_ns('signing.version', api_version='v4')
        with freeze_time('2019-04-08 15:16:23.42'):
            for _x in range(0, 3):
                self._add_fake_throttling_action(
                    view_class=self.view_class,
                    url=url,
                    user=self.user,
                    remote_addr='1.2.3.4',
                )

            # At this point we should be throttled since we're using the same
            # user. (we're still inside the frozen time context).
            response = self.request(
                'POST',
                url=url,
                guid='@create-webextension',
                version='1.0',
                extra_kwargs={
                    'REMOTE_ADDR': '1.2.3.4',
                    'HTTP_X_FORWARDED_FOR': f'1.2.3.4, {get_random_ip()}',
                },
            )
            assert response.status_code == 429, response.content
        # We should have recorded an ActivityLog.
        assert ActivityLog.objects.filter(
            user=self.user, action=amo.LOG.THROTTLED.id
        ).exists()

    def test_user_restriction_history_saved_on_permission_denied(self):
        EmailUserRestriction.objects.create(email_pattern=self.user.email)
        url = reverse_ns('signing.version', api_version='v4')
        response = self.request(
            'POST',
            url=url,
            guid='@create-webextension',
            version='1.0',
            extra_kwargs={
                'REMOTE_ADDR': '1.2.3.4',
                'HTTP_X_FORWARDED_FOR': f'1.2.3.4, {get_random_ip()}',
            },
        )
        assert response.status_code == 403, response.content
        assert UserRestrictionHistory.objects.filter(user=self.user).exists()
        restriction = UserRestrictionHistory.objects.get(user=self.user)
        assert restriction.ip_address == '1.2.3.4'
        assert restriction.last_login_ip == '1.2.3.4'
        assert restriction.get_restriction_display() == 'EmailUserRestriction'


class TestCheckVersion(BaseUploadVersionTestMixin, TestCase):
    def test_not_authenticated(self):
        # Use self.client.get so that we don't add the authorization header.
        response = self.client.get(self.url(self.guid, '12.5'))
        assert response.status_code == 401

    def test_addon_does_not_exist(self):
        response = self.get(self.url('foo', '12.5'))
        assert response.status_code == 404
        assert response.data['error'] == ('Could not find Add-on with ID "foo".')

    def test_user_does_not_own_addon(self):
        self.create_version('3.0')
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now(), email='foo@bar.com'
        )
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 403
        assert response.data['error'] == 'You do not own this add-on.'

    def test_admin_can_view(self):
        self.create_version('3.0')
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now(), email='foo@bar.com'
        )
        self.make_admin(self.user)
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

    def test_version_does_not_exist(self):
        response = self.get(self.url(self.guid, '2.5'))
        assert response.status_code == 404
        assert response.data['error'] == 'No uploaded file for that add-on and version.'

    def test_version_exists(self):
        self.create_version('3.0')
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

    def test_version_exists_with_pk(self):
        # Mock Version.from_upload so the Version won't be created.
        with mock.patch('olympia.devhub.utils.Version.from_upload'):
            self.create_version('3.0')
        upload = FileUpload.objects.latest()
        upload.update(created=datetime.today() - timedelta(hours=1))

        self.create_version('3.0')
        newer_upload = FileUpload.objects.latest()
        assert newer_upload != upload

        response = self.get(self.url(self.guid, '3.0', upload.uuid.hex))
        assert response.status_code == 200
        # For backwards-compatibility reasons, we return the uuid as "pk".
        assert response.data['pk'] == upload.uuid.hex
        assert 'processed' in response.data

    def test_version_exists_with_pk_not_owner(self):
        orig_user, orig_api_key = self.user, self.api_key

        # This will create a version for the add-on with guid @create-version
        # using a new user.
        self.user = UserProfile.objects.create(
            read_dev_agreement=datetime.now(), email='foo@bar.com'
        )
        self.api_key = self.create_api_key(self.user, 'bar')
        response = self.request('PUT', guid='@create-version', version='1.0')
        assert response.status_code == 201
        upload = FileUpload.objects.latest()

        # Check that the user that created the upload can access it properly.
        response = self.get(self.url('@create-version', '1.0', upload.uuid.hex))
        assert response.status_code == 200
        assert 'processed' in response.data

        # This will create a version for the add-on from the fixture with the
        # regular fixture user.
        self.user, self.api_key = orig_user, orig_api_key
        self.create_version('3.0')

        # Check that we can't access the FileUpload by uuid even if we pass in
        # an add-on and version that we own if we don't own the FileUpload.
        response = self.get(self.url(self.guid, '3.0', upload.uuid.hex))
        assert response.status_code == 404
        assert 'error' in response.data

    def test_version_download_url(self):
        version_string = '3.0'
        qs = File.objects.filter(
            version__addon__guid=self.guid, version__version=version_string
        )
        assert not qs.exists()
        self.create_version(version_string)
        response = self.get(self.url(self.guid, version_string))
        assert response.status_code == 200
        file_ = qs.get()
        assert response.data['files'][0]['download_url'] == absolutify(
            reverse_ns('signing.file', api_version='v4', kwargs={'file_id': file_.id})
            + f'/{file_.pretty_filename}'
        )

    def test_file_hash(self):
        version_string = '3.0'
        qs = File.objects.filter(
            version__addon__guid=self.guid, version__version=version_string
        )
        assert not qs.exists()
        self.create_version(version_string)
        response = self.get(self.url(self.guid, version_string))
        assert response.status_code == 200
        file_ = qs.get()

        # We're repackaging, so we can't compare the hash to an existing value,
        # we have to recompute it.
        with open(file_.file.path, 'rb') as f:
            expected_hash = f'sha256:{get_sha256(f)}'
        assert file_.hash == expected_hash
        assert response.data['files'][0]['hash'] == expected_hash

    def test_has_failed_upload(self):
        addon = Addon.objects.get(guid=self.guid)
        FileUpload.objects.create(
            addon=addon,
            version='3.0',
            user=self.user,
            source=amo.UPLOAD_SOURCE_SIGNING_API,
            ip_address='127.0.0.70',
            channel=amo.CHANNEL_LISTED,
        )
        self.create_version('3.0')
        response = self.get(self.url(self.guid, '3.0'))
        assert response.status_code == 200
        assert 'processed' in response.data

    def test_not_throttling_get(self):
        self.create_version('3.0')
        url = self.url(self.guid, '3.0')

        with freeze_time('2019-04-08 15:16:23.42'):
            for _x in range(0, 60):
                # With that many actions all throttling classes should prevent
                # the user from submitting an addon...
                self._add_fake_throttling_action(
                    view_class=self.view_class,
                    url=self.url(self.guid, '3.0'),
                    user=self.user,
                    remote_addr='1.2.3.4',
                )

            # ... But it works, because it's just a GET, not a POST/PUT upload.
            response = self.get(
                url,
                client_kwargs={
                    'REMOTE_ADDR': '1.2.3.4',
                    'HTTP_X_FORWARDED_FOR': f'1.2.3.4, {get_random_ip()}',
                },
            )
            assert response.status_code == 200


class TestSignedFile(SigningAPITestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.file_ = self.create_file()

    def url(self):
        return reverse_ns('signing.file', api_version='v4', args=[self.file_.pk])

    def create_file(self):
        addon = addon_factory(
            name='thing',
            version_kw={'channel': amo.CHANNEL_UNLISTED},
            users=[self.user],
            file_kw={'filename': 'webextension.xpi'},
        )
        return addon.latest_unlisted_version.file

    def test_can_download_once_authenticated(self):
        response = self.get(self.url())
        assert response.status_code == 200
        assert response[settings.XSENDFILE_HEADER] == (self.file_.file.path)

    def test_cannot_download_without_authentication(self):
        response = self.client.get(self.url())  # no auth
        assert response.status_code == 401

    def test_api_relies_on_version_downloader(self):
        with mock.patch('olympia.versions.views.download_file') as df:
            df.return_value = Response({})
            self.get(self.url())
        assert df.called is True
        assert df.call_args[0][0].user == self.user
        assert df.call_args[0][1] == str(self.file_.pk)
