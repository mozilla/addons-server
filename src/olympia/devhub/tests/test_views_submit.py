import io
import json
import os
import stat
import tarfile
import zipfile
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from unittest import mock
from urllib.parse import urlencode

from django.conf import settings
from django.core.files import temp
from django.core.files.storage import default_storage as storage
from django.test.utils import override_settings
from django.urls import reverse

import responses
from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo
from olympia.accounts.utils import fxa_login_url
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonCategory, AddonReviewerFlags
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    create_default_webext_appversion,
    initial,
    version_factory,
)
from olympia.constants.categories import CATEGORIES
from olympia.constants.licenses import LICENSES_BY_BUILTIN
from olympia.constants.promoted import NOTABLE, RECOMMENDED
from olympia.devhub import views
from olympia.files.tests.test_models import UploadMixin
from olympia.files.utils import parse_addon
from olympia.users.models import IPNetworkUserRestriction, UserProfile
from olympia.versions.models import (
    AppVersion,
    License,
    VersionPreview,
    VersionProvenance,
)
from olympia.versions.utils import get_review_due_date
from olympia.zadmin.models import Config, set_config


STRING_QUOTE_OPEN = '“'
STRING_QUOTE_CLOSE = '”'


def get_addon_count(name):
    """Return the number of addons with the given name."""
    return Addon.unfiltered.filter(name__localized_string=name).count()


def _parse_addon_theme_permission_wrapper(*args, **kwargs):
    parsed = parse_addon(*args, **kwargs)
    parsed['permissions'] = parsed.get('permissions', []) + ['theme']
    return parsed


class TestSubmitBase(TestCase):
    fixtures = ['base/addon_3615', 'base/addon_5579', 'base/users']

    def setUp(self):
        super().setUp()
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.client.force_login_with_2fa(self.user)
        self.user.update(last_login_ip='192.0.2.1')
        self.addon = self.get_addon()
        self.create_flag('2fa-enforcement-for-developers-and-special-users')

    def get_addon(self):
        return Addon.objects.get(pk=3615)

    def get_version(self):
        return self.get_addon().versions.latest()

    def generate_source_zip(
        self, suffix='.zip', data='z' * (2**21), compression=zipfile.ZIP_DEFLATED
    ):
        tdir = temp.gettempdir()
        source = temp.NamedTemporaryFile(suffix=suffix, dir=tdir)
        with zipfile.ZipFile(source, 'w', compression=compression) as zip_file:
            zip_file.writestr('foo', data)
        source.seek(0)
        return source

    def generate_source_tar(self, suffix='.tar.gz', data=b't' * (2**21), mode=None):
        tdir = temp.gettempdir()
        source = temp.NamedTemporaryFile(suffix=suffix, dir=tdir)
        if mode is None:
            mode = 'w:bz2' if suffix.endswith('.tar.bz2') else 'w:gz'
        with tarfile.open(fileobj=source, mode=mode) as tar_file:
            tar_info = tarfile.TarInfo('foo')
            tar_info.size = len(data)
            tar_file.addfile(tar_info, io.BytesIO(data))

        source.seek(0)
        return source

    def generate_source_garbage(self, suffix='.zip', data=b'g' * (2**21)):
        tdir = temp.gettempdir()
        source = temp.NamedTemporaryFile(suffix=suffix, dir=tdir)
        source.write(data)
        source.seek(0)
        return source


class TestAddonSubmitAgreement(TestSubmitBase):
    def setUp(self):
        self.url = reverse('devhub.submit.agreement')
        self.next_url = reverse('devhub.submit.distribution')
        super().setUp()

    def test_set_read_dev_agreement(self):
        response = self.client.post(
            self.url,
            {
                'distribution_agreement': 'on',
                'review_policy': 'on',
            },
        )
        self.assert3xx(response, self.next_url)
        self.user.reload()
        self.assertCloseToNow(self.user.read_dev_agreement)

    def test_set_read_dev_agreement_theme(self):
        self.client.logout()  # Shouldn't need 2FA.
        self.client.force_login(self.user)
        # Make sure we still have a last login ip though.
        self.user.update(last_login_ip='192.0.2.1')
        self.url = reverse('devhub.submit.theme.agreement')
        self.next_url = reverse('devhub.submit.theme.distribution')
        response = self.client.post(
            self.url,
            {
                'distribution_agreement': 'on',
                'review_policy': 'on',
            },
        )
        self.assert3xx(response, self.next_url)
        self.user.reload()
        self.assertCloseToNow(self.user.read_dev_agreement)

    def test_set_read_dev_agreement_error(self):
        set_config('last_dev_agreement_change_date', '2019-06-10 00:00')
        before_agreement_last_changed = datetime(2019, 6, 10) - timedelta(days=1)
        self.user.update(read_dev_agreement=before_agreement_last_changed)
        response = self.client.post(self.url)
        assert response.status_code == 200
        assert 'agreement_form' in response.context
        form = response.context['agreement_form']
        assert form.is_valid() is False
        assert form.errors == {
            'distribution_agreement': ['This field is required.'],
            'review_policy': ['This field is required.'],
        }
        doc = pq(response.content)
        for id_ in form.errors.keys():
            selector = 'li input#id_%s + a + .errorlist' % id_
            assert doc(selector).text() == 'This field is required.'

    def test_read_dev_agreement_skip(self):
        set_config('last_dev_agreement_change_date', '2019-06-10 00:00')
        after_agreement_last_changed = datetime(2019, 6, 10) + timedelta(days=1)
        self.user.update(read_dev_agreement=after_agreement_last_changed)
        response = self.client.get(self.url)
        self.assert3xx(response, self.next_url)

    @override_settings(DEV_AGREEMENT_CHANGE_FALLBACK=datetime(2019, 6, 10, 12, 00))
    def test_read_dev_agreement_fallback_with_config_set_to_future(self):
        set_config('last_dev_agreement_change_date', '2099-12-31 00:00')
        read_dev_date = datetime(2019, 6, 11)
        self.user.update(read_dev_agreement=read_dev_date)
        response = self.client.get(self.url)
        self.assert3xx(response, self.next_url)

    def test_read_dev_agreement_fallback_with_conf_future_and_not_agreed(self):
        set_config('last_dev_agreement_change_date', '2099-12-31 00:00')
        self.user.update(read_dev_agreement=None)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert 'agreement_form' in response.context

    @override_settings(DEV_AGREEMENT_CHANGE_FALLBACK=datetime(2019, 6, 10, 12, 00))
    def test_read_dev_agreement_invalid_date_agreed_post_fallback(self):
        set_config('last_dev_agreement_change_date', '2099-25-75 00:00')
        read_dev_date = datetime(2019, 6, 11)
        self.user.update(read_dev_agreement=read_dev_date)
        response = self.client.get(self.url)
        self.assert3xx(response, self.next_url)

    def test_read_dev_agreement_invalid_date_not_agreed_post_fallback(self):
        set_config('last_dev_agreement_change_date', '2099,31,12,0,0')
        self.user.update(read_dev_agreement=None)
        response = self.client.get(self.url)
        self.assertRaises(ValueError)
        assert response.status_code == 200
        assert 'agreement_form' in response.context

    def test_read_dev_agreement_no_date_configured_agreed_post_fallback(self):
        response = self.client.get(self.url)
        self.assert3xx(response, self.next_url)

    def test_read_dev_agreement_no_date_configured_not_agreed_post_fallb(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert 'agreement_form' in response.context

    def test_read_dev_agreement_captcha_inactive(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(self.url)
        assert response.status_code == 200
        form = response.context['agreement_form']
        assert 'recaptcha' not in form.fields

        doc = pq(response.content)
        assert doc('.g-recaptcha') == []

    @override_switch('developer-agreement-captcha', active=True)
    def test_read_dev_agreement_captcha_active_error(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(self.url)
        assert response.status_code == 200
        form = response.context['agreement_form']
        assert 'recaptcha' in form.fields

        response = self.client.post(self.url)

        # Captcha is properly rendered
        doc = pq(response.content)
        assert doc('.g-recaptcha')

        assert 'recaptcha' in response.context['agreement_form'].errors

    @override_switch('developer-agreement-captcha', active=True)
    def test_read_dev_agreement_captcha_active_success(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(self.url)
        assert response.status_code == 200
        form = response.context['agreement_form']
        assert 'recaptcha' in form.fields
        # Captcha is also properly rendered
        doc = pq(response.content)
        assert doc('.g-recaptcha')

        verify_data = urlencode(
            {
                'secret': '',
                'remoteip': '127.0.0.1',
                'response': 'test',
            }
        )

        responses.add(
            responses.GET,
            'https://www.google.com/recaptcha/api/siteverify?' + verify_data,
            json={'error-codes': [], 'success': True},
        )

        response = self.client.post(
            self.url,
            data={
                'g-recaptcha-response': 'test',
                'distribution_agreement': 'on',
                'review_policy': 'on',
            },
        )
        self.assert3xx(response, self.next_url)

    def test_cant_submit_agreement_if_restricted_functional(self):
        IPNetworkUserRestriction.objects.create(network='127.0.0.1/32')
        self.user.update(read_dev_agreement=None)
        response = self.client.post(
            self.url,
            data={
                'distribution_agreement': 'on',
                'review_policy': 'on',
            },
        )
        assert response.status_code == 200
        assert response.context['agreement_form'].is_valid() is False
        doc = pq(response.content)
        assert (
            doc('.addon-submission-process')
            .text()
            .endswith(
                'Multiple submissions violating our policies have been sent '
                'from your location. The IP address has been blocked.\n'
                'More information on Developer Accounts'
            )
        )

    def test_display_name_already_set_not_asked_again(self):
        self.user.update(read_dev_agreement=None, display_name='Foo')
        response = self.client.get(self.url)
        assert response.status_code == 200
        form = response.context['agreement_form']
        assert 'display_name' not in form.fields
        response = self.client.post(
            self.url,
            data={
                'distribution_agreement': 'on',
                'review_policy': 'on',
            },
        )
        self.assert3xx(response, self.next_url)
        assert self.user.reload().read_dev_agreement

    def test_display_name_required(self):
        self.user.update(read_dev_agreement=None, display_name='')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        form = response.context['agreement_form']
        assert 'display_name' in form.fields
        assert (
            'Your account needs a display name'
            in doc('.addon-submission-process').text()
        )
        response = self.client.post(
            self.url,
            data={
                'distribution_agreement': 'on',
                'review_policy': 'on',
            },
        )
        assert response.status_code == 200
        assert response.context['agreement_form'].is_valid() is False
        assert response.context['agreement_form'].errors == {
            'display_name': ['This field is required.']
        }
        doc = pq(response.content)
        assert doc('.addon-submission-process .errorlist')
        assert not self.user.reload().read_dev_agreement

    def test_display_name_submission(self):
        self.user.update(read_dev_agreement=None, display_name='')
        response = self.client.post(
            self.url,
            data={
                'distribution_agreement': 'on',
                'review_policy': 'on',
                'display_name': 'ö',  # Too short.
            },
        )
        assert response.status_code == 200
        assert response.context['agreement_form'].is_valid() is False
        assert response.context['agreement_form'].errors == {
            'display_name': ['Ensure this value has at least 2 characters (it has 1).']
        }

        response = self.client.post(
            self.url,
            data={
                'distribution_agreement': 'on',
                'review_policy': 'on',
                'display_name': '\n\n\n',  # Only contains non-printable chars
            },
        )
        assert response.status_code == 200
        assert response.context['agreement_form'].is_valid() is False
        assert response.context['agreement_form'].errors == {
            'display_name': ['This field is required.']
        }

        response = self.client.post(
            self.url,
            data={
                'distribution_agreement': 'on',
                'review_policy': 'on',
                'display_name': 'Fôä',
            },
        )
        self.assert3xx(response, self.next_url)
        self.user.reload()
        self.assertCloseToNow(self.user.read_dev_agreement)
        assert self.user.display_name == 'Fôä'

    def test_enforce_2fa(self):
        self.user.update(read_dev_agreement=None)
        self.client.logout()
        self.client.force_login(self.user)
        self.user.update(last_login_ip='192.0.2.1')
        response = self.client.get(self.url)
        expected_location = fxa_login_url(
            config=settings.FXA_CONFIG['default'],
            state=self.client.session['fxa_state'],
            next_path=self.url,
            enforce_2fa=True,
            login_hint=self.user.email,
        )
        self.assert3xx(response, expected_location)


class TestAddonSubmitDistribution(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.client.force_login_with_2fa(self.user)
        self.user.update(last_login_ip='192.0.2.1')
        self.url = reverse('devhub.submit.distribution')
        self.create_flag('2fa-enforcement-for-developers-and-special-users')

    def test_check_agreement_okay(self):
        response = self.client.post(reverse('devhub.submit.agreement'))
        self.assert3xx(response, self.url)
        response = self.client.get(self.url)
        assert response.status_code == 200
        # No error shown for a redirect from previous step.
        assert b'This field is required' not in response.content

    def test_submit_notification_warning(self):
        config = Config.objects.create(
            key='submit_notification_warning',
            value='Text with <a href="http://example.com">a link</a>.',
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.notification-box.warning').html().strip() == config.value

    def test_redirect_back_to_agreement(self):
        self.user.update(read_dev_agreement=None)

        response = self.client.get(self.url, follow=True)
        self.assert3xx(response, reverse('devhub.submit.agreement'))

        # read_dev_agreement needs to be a more recent date than
        # the setting.
        set_config('last_dev_agreement_change_date', '2019-06-10 00:00')
        before_agreement_last_changed = datetime(2019, 6, 10) - timedelta(days=1)
        self.user.update(read_dev_agreement=before_agreement_last_changed)
        response = self.client.get(self.url, follow=True)
        self.assert3xx(response, reverse('devhub.submit.agreement'))

    def test_redirect_back_to_agreement_theme(self):
        self.user.update(read_dev_agreement=None)

        response = self.client.get(
            reverse('devhub.submit.theme.distribution'), follow=True
        )
        self.assert3xx(response, reverse('devhub.submit.theme.agreement'))

        # read_dev_agreement needs to be a more recent date than
        # the setting.
        set_config('last_dev_agreement_change_date', '2019-06-10 00:00')
        before_agreement_last_changed = datetime(2019, 6, 10) - timedelta(days=1)
        self.user.update(read_dev_agreement=before_agreement_last_changed)
        response = self.client.get(
            reverse('devhub.submit.theme.distribution'), follow=True
        )
        self.assert3xx(response, reverse('devhub.submit.theme.agreement'))

    def test_redirect_back_to_agreement_if_restricted(self):
        IPNetworkUserRestriction.objects.create(network='127.0.0.1/32')
        response = self.client.get(self.url, follow=True)
        self.assert3xx(response, reverse('devhub.submit.agreement'))

    def test_listed_redirects_to_next_step(self):
        response = self.client.post(self.url, {'channel': 'listed'})
        self.assert3xx(response, reverse('devhub.submit.upload', args=['listed']))

    def test_unlisted_redirects_to_next_step(self):
        response = self.client.post(self.url, {'channel': 'unlisted'})
        self.assert3xx(response, reverse('devhub.submit.upload', args=['unlisted']))

    def test_listed_redirects_to_next_step_theme(self):
        response = self.client.post(
            reverse('devhub.submit.theme.distribution'), {'channel': 'listed'}
        )
        self.assert3xx(response, reverse('devhub.submit.theme.upload', args=['listed']))

    def test_channel_selection_error_shown(self):
        url = self.url
        # First load should have no error
        assert b'This field is required' not in self.client.get(url).content

        # Load with channel preselected (e.g. back from next step) - no error.
        assert (
            b'This field is required'
            not in self.client.get(url, args=['listed']).content
        )

        # A post submission without channel selection should be an error
        assert b'This field is required' in self.client.post(url).content

    def test_enforce_2fa(self):
        self.client.logout()
        self.client.force_login(self.user)
        self.user.update(last_login_ip='192.168.42.43')
        response = self.client.get(self.url)
        expected_location = fxa_login_url(
            config=settings.FXA_CONFIG['default'],
            state=self.client.session['fxa_state'],
            next_path=self.url,
            enforce_2fa=True,
            login_hint=self.user.email,
        )
        self.assert3xx(response, expected_location)


@override_settings(REPUTATION_SERVICE_URL=None)
class TestAddonSubmitUpload(UploadMixin, TestCase):
    fixtures = ['base/users']

    @classmethod
    def setUpTestData(cls):
        create_default_webext_appversion()

    def setUp(self):
        super().setUp()
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.client.force_login_with_2fa(self.user)
        self.user.update(last_login_ip='192.0.2.1')
        self.upload = self.get_upload('webextension_no_id.xpi', user=self.user)
        self.statsd_incr_mock = self.patch('olympia.devhub.views.statsd.incr')
        self.create_flag('2fa-enforcement-for-developers-and-special-users')

    def post(
        self,
        compatible_apps=None,
        expect_errors=False,
        listed=True,
        status_code=200,
        url=None,
        theme=False,
        extra_kwargs=None,
    ):
        if compatible_apps is None:
            compatible_apps = [amo.FIREFOX, amo.ANDROID]
        data = {
            'upload': self.upload.uuid.hex,
            'compatible_apps': [p.id for p in compatible_apps],
        }
        urlname = 'devhub.submit.upload' if not theme else 'devhub.submit.theme.upload'
        url = url or reverse(urlname, args=['listed' if listed else 'unlisted'])
        response = self.client.post(url, data, follow=True, **(extra_kwargs or {}))
        assert response.status_code == status_code
        if not expect_errors:
            # Show any unexpected form errors.
            if response.context and 'new_addon_form' in response.context:
                assert response.context['new_addon_form'].errors.as_text() == ''
        return response

    def test_redirect_back_to_agreement_if_restricted(self):
        url = reverse('devhub.submit.upload', args=['listed'])
        IPNetworkUserRestriction.objects.create(network='127.0.0.1/32')
        response = self.client.post(url, follow=False)
        self.assert3xx(response, reverse('devhub.submit.agreement'))

        url = reverse('devhub.submit.upload', args=['unlisted'])
        response = self.client.post(url, follow=False)
        self.assert3xx(response, reverse('devhub.submit.agreement'))

    @override_settings(
        REPUTATION_SERVICE_URL='https://reputation.example.com',
        REPUTATION_SERVICE_TOKEN='some_token',
    )
    def test_redirect_back_to_agreement_if_restricted_by_reputation(self):
        assert Addon.objects.count() == 0
        responses.add(
            responses.GET,
            'https://reputation.example.com/type/ip/127.0.0.1',
            content_type='application/json',
            json={'reputation': 45},
        )
        responses.add(
            responses.GET,
            'https://reputation.example.com/type/email/regular@mozilla.com',
            content_type='application/json',
            status=404,
        )
        url = reverse('devhub.submit.upload', args=['unlisted'])
        response = self.client.post(url, follow=False)
        self.assert3xx(response, reverse('devhub.submit.agreement'))
        assert len(responses.calls) == 2
        assert Addon.objects.count() == 0

    def test_unique_name(self):
        addon_factory(name='Beastify')
        self.post(expect_errors=False)

    def test_unlisted_name_not_unique(self):
        """We don't enforce name uniqueness for unlisted add-ons."""
        addon_factory(name='Beastify', version_kw={'channel': amo.CHANNEL_LISTED})
        assert get_addon_count('Beastify') == 1
        # We're not passing `expected_errors=True`, so if there was any errors
        # like "This name is already in use. Please choose another one", the
        # test would fail.
        response = self.post()
        # Kind of redundant with the `self.post()` above: we just want to make
        # really sure there's no errors raised by posting an add-on with a name
        # that is already used by an unlisted add-on.
        assert 'new_addon_form' not in response.context
        assert get_addon_count('Beastify') == 2

    def test_name_not_unique_between_types(self):
        """We don't enforce name uniqueness between add-ons types."""
        addon_factory(name='Beastify', type=amo.ADDON_STATICTHEME)
        assert get_addon_count('Beastify') == 1
        # We're not passing `expected_errors=True`, so if there was any errors
        # like "This name is already in use. Please choose another one", the
        # test would fail.
        response = self.post(theme=True)
        # Kind of redundant with the `self.post()` above: we just want to make
        # really sure there's no errors raised by posting an add-on with a name
        # that is already used by an unlisted add-on.
        assert 'new_addon_form' not in response.context
        assert get_addon_count('Beastify') == 2

    def test_success_listed(self):
        assert Addon.objects.count() == 0
        response = self.post()
        addon = Addon.objects.get()
        version = addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        assert version
        assert version.channel == amo.CHANNEL_LISTED
        self.assert3xx(
            response, reverse('devhub.submit.source', args=[addon.slug, 'listed'])
        )
        log_items = ActivityLog.objects.for_addons(addon)
        assert log_items.filter(
            action=amo.LOG.CREATE_ADDON.id
        ), 'New add-on creation never logged.'
        self.statsd_incr_mock.assert_any_call('devhub.submission.addon.listed')
        provenance = VersionProvenance.objects.get()
        assert provenance.version == version
        assert provenance.source == amo.UPLOAD_SOURCE_DEVHUB
        assert provenance.client_info is None

    def test_success_custom_user_agent(self):
        assert Addon.objects.count() == 0
        response = self.post(extra_kwargs={'HTTP_USER_AGENT': 'Löl/42.0'})
        addon = Addon.objects.get()
        version = addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        assert version
        assert version.channel == amo.CHANNEL_LISTED
        self.assert3xx(
            response, reverse('devhub.submit.source', args=[addon.slug, 'listed'])
        )
        log_items = ActivityLog.objects.for_addons(addon)
        assert log_items.filter(
            action=amo.LOG.CREATE_ADDON.id
        ), 'New add-on creation never logged.'
        self.statsd_incr_mock.assert_any_call('devhub.submission.addon.listed')
        provenance = VersionProvenance.objects.get()
        assert provenance.version == version
        assert provenance.source == amo.UPLOAD_SOURCE_DEVHUB
        assert provenance.client_info == 'Löl/42.0'

    def test_success_unlisted(self):
        assert Addon.objects.count() == 0
        # No validation errors or warning.
        result = {
            'errors': 0,
            'warnings': 0,
            'notices': 2,
            'metadata': {},
            'messages': [],
        }
        self.upload = self.get_upload(
            'webextension.xpi', validation=json.dumps(result), user=self.user
        )
        response = self.post(listed=False)
        addon = Addon.objects.get()
        version = addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)
        assert version
        assert version.file.status == amo.STATUS_AWAITING_REVIEW
        assert version.channel == amo.CHANNEL_UNLISTED
        assert addon.status == amo.STATUS_NULL
        self.assert3xx(
            response, reverse('devhub.submit.source', args=[addon.slug, 'unlisted'])
        )
        self.statsd_incr_mock.assert_any_call('devhub.submission.addon.unlisted')
        provenance = VersionProvenance.objects.get()
        assert provenance.version == version
        assert provenance.source == amo.UPLOAD_SOURCE_DEVHUB
        assert provenance.client_info is None

    def test_missing_compatible_apps(self):
        url = reverse('devhub.submit.upload', args=['listed'])
        response = self.client.post(url, {'upload': self.upload.uuid.hex})
        assert response.status_code == 200
        assert response.context['new_addon_form'].errors.as_text() == (
            '* compatible_apps\n  * Need to select at least one application.'
        )
        doc = pq(response.content)
        assert doc('ul.errorlist').text() == (
            'Need to select at least one application.'
        )

    def test_compatible_apps_gecko_android_in_manifest(self):
        # Only specifying firefox compatibility for an add-on that has explicit
        # gecko_android compatibility in manifest is accepted, but we
        # automatically add Android compatibility.
        self.upload = self.get_upload('webextension_gecko_android.xpi', user=self.user)
        url = reverse('devhub.submit.upload', args=['listed'])
        response = self.client.post(
            url,
            {
                'upload': self.upload.uuid.hex,
                'compatible_apps': [amo.FIREFOX.id],
            },
        )
        assert response.status_code == 302
        addon = Addon.objects.latest('pk')
        assert addon.current_version.apps.count() == 2
        assert (
            addon.current_version.compatible_apps[amo.FIREFOX].originated_from
            == amo.APPVERSIONS_ORIGINATED_FROM_DEVELOPER
        )
        assert (
            addon.current_version.compatible_apps[amo.ANDROID].originated_from
            == amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID
        )
        assert (
            addon.current_version.compatible_apps[amo.ANDROID].min.version
            == amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY
        )

    def test_theme_variant_has_theme_stuff_visible(self):
        self.client.logout()  # Shouldn't need 2FA.
        self.client.force_login(self.user)
        # Make sure we still have a last login ip though.
        self.user.update(last_login_ip='192.0.2.1')
        response = self.client.get(
            reverse('devhub.submit.theme.upload', args=['listed']), follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#wizardlink')
        assert doc('#wizardlink').attr('href') == (
            reverse('devhub.submit.wizard', args=['listed'])
        )
        assert doc('#id_theme_specific').attr('value') == 'True'

        response = self.client.get(
            reverse('devhub.submit.theme.upload', args=['unlisted']), follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#wizardlink')
        assert doc('#wizardlink').attr('href') == (
            reverse('devhub.submit.wizard', args=['unlisted'])
        )
        assert doc('#id_theme_specific').attr('value') == 'True'

    def test_non_theme_variant_has_theme_stuff_hidden(self):
        response = self.client.get(
            reverse('devhub.submit.upload', args=['listed']), follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#wizardlink')
        assert doc('#id_theme_specific').attr('value') == 'False'

        response = self.client.get(
            reverse('devhub.submit.upload', args=['unlisted']), follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#wizardlink')
        assert doc('#id_theme_specific').attr('value') == 'False'

    def test_static_theme_submit_listed(self):
        assert Addon.objects.count() == 0
        path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip'
        )
        self.upload = self.get_upload(abspath=path, user=self.user)
        response = self.post(theme=True)
        addon = Addon.objects.get()
        self.assert3xx(response, reverse('devhub.submit.details', args=[addon.slug]))
        assert addon.current_version.file.file.name.endswith(
            f'{addon.pk}/weta_fade-2.9.zip'
        )
        assert addon.type == amo.ADDON_STATICTHEME
        previews = list(addon.current_version.previews.all())
        assert len(previews) == 2
        assert storage.exists(previews[0].image_path)
        assert storage.exists(previews[1].image_path)

    def test_static_theme_submit_unlisted(self):
        assert Addon.unfiltered.count() == 0
        path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip'
        )
        self.upload = self.get_upload(abspath=path, user=self.user)
        response = self.post(listed=False, theme=True)
        addon = Addon.unfiltered.get()
        latest_version = addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)
        self.assert3xx(response, reverse('devhub.submit.finish', args=[addon.slug]))
        assert latest_version.file.file.name.endswith(
            f'{addon.pk}/{addon.slug}-2.9.zip'
        )
        assert addon.type == amo.ADDON_STATICTHEME
        # Only listed submissions need a preview generated.
        assert latest_version.previews.all().count() == 0

    def test_static_theme_wizard_listed(self):
        # Check we get the correct template.
        url = reverse('devhub.submit.wizard', args=['listed'])
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#theme-wizard')
        assert doc('#theme-wizard').attr('data-version') == '1.0'
        assert doc('input#theme-name').attr('type') == 'text'

        # And then check the upload works.  In reality the zip is generated
        # client side in JS but the zip file is the same.
        assert Addon.objects.count() == 0
        path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip'
        )
        self.upload = self.get_upload(abspath=path, user=self.user)
        response = self.post(url=url)
        addon = Addon.objects.get()
        # Next step is same as non-wizard flow too.
        self.assert3xx(response, reverse('devhub.submit.details', args=[addon.slug]))
        assert addon.current_version.file.file.name.endswith(
            f'{addon.pk}/weta_fade-2.9.zip'
        )
        assert addon.type == amo.ADDON_STATICTHEME
        previews = list(addon.current_version.previews.all())
        assert len(previews) == 2
        assert storage.exists(previews[0].image_path)
        assert storage.exists(previews[1].image_path)

    def test_static_theme_wizard_unlisted(self):
        # Check we get the correct template.
        url = reverse('devhub.submit.wizard', args=['unlisted'])
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#theme-wizard')
        assert doc('#theme-wizard').attr('data-version') == '1.0'
        assert doc('input#theme-name').attr('type') == 'text'

        # And then check the upload works.  In reality the zip is generated
        # client side in JS but the zip file is the same.
        assert Addon.unfiltered.count() == 0
        path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip'
        )
        self.upload = self.get_upload(abspath=path, user=self.user)
        response = self.post(url=url, listed=False)
        addon = Addon.unfiltered.get()
        latest_version = addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)
        # Next step is same as non-wizard flow too.
        self.assert3xx(response, reverse('devhub.submit.finish', args=[addon.slug]))
        assert latest_version.file.file.name.endswith(
            f'{addon.pk}/{addon.slug}-2.9.zip'
        )
        assert addon.type == amo.ADDON_STATICTHEME
        # Only listed submissions need a preview generated.
        assert latest_version.previews.all().count() == 0

    def test_enforce_2fa(self):
        self.client.logout()
        self.client.force_login(self.user)
        self.user.update(last_login_ip='192.168.45.47')
        self.url = reverse('devhub.submit.upload', args=['listed'])
        response = self.client.get(self.url)
        expected_location = fxa_login_url(
            config=settings.FXA_CONFIG['default'],
            state=self.client.session['fxa_state'],
            next_path=self.url,
            enforce_2fa=True,
            login_hint=self.user.email,
        )
        self.assert3xx(response, expected_location)

        self.url = reverse('devhub.submit.upload', args=['unlisted'])
        response = self.client.get(self.url)
        expected_location = fxa_login_url(
            config=settings.FXA_CONFIG['default'],
            state=self.client.session['fxa_state'],
            next_path=self.url,
            enforce_2fa=True,
            login_hint=self.user.email,
        )
        self.assert3xx(response, expected_location)

    def test_android_compatibility_modal(self):
        url = reverse('devhub.submit.upload', args=['listed'])
        modal_selector = '#modals #modal-confirm-android-compatibility.modal'
        response = self.client.get(url)
        doc = pq(response.content)
        assert doc(modal_selector)


class TestAddonSubmitSource(TestSubmitBase):
    def setUp(self):
        super().setUp()
        assert not self.get_version().source
        self.url = reverse('devhub.submit.source', args=[self.addon.slug, 'listed'])
        self.next_url = reverse('devhub.submit.details', args=[self.addon.slug])

    def post(self, has_source, source, expect_errors=False, status_code=200):
        data = {
            'has_source': 'yes' if has_source else 'no',
        }
        if source is not None:
            data['source'] = source
        response = self.client.post(self.url, data, follow=True)
        assert response.status_code == status_code
        if not expect_errors:
            # Show any unexpected form errors.
            if response.context and 'source_form' in response.context:
                assert response.context['source_form'].errors == {}
        return response

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=1)
    def test_submit_source(self):
        response = self.post(has_source=True, source=self.generate_source_zip())
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert self.get_version().source
        assert str(self.get_version().source).endswith('.zip')
        mode = '0%o' % (os.stat(self.get_version().source.path)[stat.ST_MODE])
        assert mode == '0100644'

    @mock.patch('olympia.devhub.views.log')
    def test_logging(self, log_mock):
        response = self.post(has_source=True, source=self.generate_source_zip())
        self.assert3xx(response, self.next_url)
        assert log_mock.info.call_count == 4
        assert log_mock.info.call_args_list[0][0] == (
            '_submit_source, form populated, addon.slug: %s, version.pk: %s',
            self.addon.slug,
            self.get_version().pk,
        )
        assert log_mock.info.call_args_list[1][0] == (
            '_submit_source, form validated, addon.slug: %s, version.pk: %s',
            self.addon.slug,
            self.get_version().pk,
        )
        assert log_mock.info.call_args_list[2][0] == (
            '_submit_source, form saved, addon.slug: %s, version.pk: %s',
            self.addon.slug,
            self.get_version().pk,
        )
        assert log_mock.info.call_args_list[3][0] == (
            '_submit_source, redirecting to next view, addon.slug: %s, version.pk: %s',
            self.addon.slug,
            self.get_version().pk,
        )

    @mock.patch('olympia.devhub.views.log')
    def test_no_logging_on_initial_display(self, log_mock):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert log_mock.info.call_count == 0

    @mock.patch('olympia.devhub.views.log')
    def test_no_logging_without_source(self, log_mock):
        response = self.post(has_source=False, source=None)
        self.assert3xx(response, self.next_url)
        assert log_mock.info.call_count == 0

    @mock.patch('olympia.devhub.views.log')
    def test_logging_failed_validation(self, log_mock):
        # Not including a source file when expected to fail validation.
        response = self.post(has_source=True, source=None, expect_errors=True)
        assert response.context['source_form'].errors == {
            'source': ['You have not uploaded a source file.']
        }
        assert log_mock.info.call_count == 2
        assert log_mock.info.call_args_list[0][0] == (
            '_submit_source, form populated, addon.slug: %s, version.pk: %s',
            self.addon.slug,
            self.get_version().pk,
        )
        assert log_mock.info.call_args_list[1][0] == (
            '_submit_source, validation failed, re-displaying the template, '
            + 'addon.slug: %s, version.pk: %s',
            self.addon.slug,
            self.get_version().pk,
        )

    def test_submit_source_targz(self):
        response = self.post(has_source=True, source=self.generate_source_tar())
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert self.get_version().source
        assert str(self.get_version().source).endswith('.tar.gz')
        mode = '0%o' % (os.stat(self.get_version().source.path)[stat.ST_MODE])
        assert mode == '0100644'

    def test_submit_source_tgz(self):
        response = self.post(
            has_source=True, source=self.generate_source_tar(suffix='.tgz')
        )
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert self.get_version().source
        assert str(self.get_version().source).endswith('.tgz')
        mode = '0%o' % (os.stat(self.get_version().source.path)[stat.ST_MODE])
        assert mode == '0100644'

    def test_submit_source_tarbz2(self):
        response = self.post(
            has_source=True, source=self.generate_source_tar(suffix='.tar.bz2')
        )
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert self.get_version().source
        assert str(self.get_version().source).endswith('.tar.bz2')
        mode = '0%o' % (os.stat(self.get_version().source.path)[stat.ST_MODE])
        assert mode == '0100644'

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=1)
    def test_say_no_but_submit_source_anyway_fails(self):
        response = self.post(
            has_source=False, source=self.generate_source_zip(), expect_errors=True
        )
        assert response.context['source_form'].errors == {
            'source': ['Source file uploaded but you indicated no source was needed.']
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source

    def test_say_yes_but_dont_submit_source_fails(self):
        response = self.post(has_source=True, source=None, expect_errors=True)
        assert response.context['source_form'].errors == {
            'source': ['You have not uploaded a source file.']
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=2**22)
    def test_submit_source_in_memory_upload(self):
        source = self.generate_source_zip()
        source_size = os.stat(source.name)[stat.ST_SIZE]
        assert source_size < settings.FILE_UPLOAD_MAX_MEMORY_SIZE
        response = self.post(has_source=True, source=source)
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert self.get_version().source
        mode = '0%o' % (os.stat(self.get_version().source.path)[stat.ST_MODE])
        assert mode == '0100644'

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=2**22)
    def test_submit_source_in_memory_upload_with_targz(self):
        source = self.generate_source_tar()
        source_size = os.stat(source.name)[stat.ST_SIZE]
        assert source_size < settings.FILE_UPLOAD_MAX_MEMORY_SIZE
        response = self.post(has_source=True, source=source)
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert self.get_version().source
        mode = '0%o' % (os.stat(self.get_version().source.path)[stat.ST_MODE])
        assert mode == '0100644'

    def test_with_bad_source_extension(self):
        response = self.post(
            has_source=True,
            source=self.generate_source_zip(suffix='.exe'),
            expect_errors=True,
        )
        assert response.context['source_form'].errors == {
            'source': [
                'Unsupported file type, please upload an archive file '
                '(.zip, .tar.gz, .tgz, .tar.bz2).'
            ],
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source

    def test_with_non_compressed_tar(self):
        response = self.post(
            # Generate a .tar.gz which is actually not compressed.
            has_source=True,
            source=self.generate_source_tar(mode='w'),
            expect_errors=True,
        )
        assert response.context['source_form'].errors == {
            'source': ['Invalid or broken archive.'],
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source

    def test_with_bad_source_not_an_actual_archive(self):
        response = self.post(
            has_source=True,
            source=self.generate_source_garbage(suffix='.zip'),
            expect_errors=True,
        )
        assert response.context['source_form'].errors == {
            'source': ['Invalid or broken archive.'],
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source

    def test_with_bad_source_broken_archive(self):
        source = self.generate_source_zip(
            data='Hello World', compression=zipfile.ZIP_STORED
        )
        data = source.read().replace(b'Hello World', b'dlroW olleH')
        source.seek(0)  # First seek to rewrite from the beginning
        source.write(data)
        source.seek(0)  # Second seek to reset like it's fresh.
        # Still looks like a zip at first glance.
        assert zipfile.is_zipfile(source)
        source.seek(0)  # Last seek to reset source descriptor before posting.
        response = self.post(has_source=True, source=source, expect_errors=True)
        assert response.context['source_form'].errors == {
            'source': ['Invalid or broken archive.'],
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source

    def test_with_bad_source_broken_archive_compressed_tar(self):
        source = self.generate_source_tar()
        with open(source.name, 'r+b') as fobj:
            fobj.truncate(512)
        # Still looks like a tar at first glance.
        assert tarfile.is_tarfile(source.name)
        # Re-open and post.
        with open(source.name, 'rb'):
            response = self.post(has_source=True, source=source, expect_errors=True)
        assert response.context['source_form'].errors == {
            'source': ['Invalid or broken archive.'],
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source

    def test_no_source(self):
        response = self.post(has_source=False, source=None)
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert not self.get_version().source

    def test_non_extension_redirects_past_to_details(self):
        # static themes should redirect
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        self.assert3xx(response, self.next_url)
        # extensions shouldn't redirect
        self.addon.update(type=amo.ADDON_EXTENSION)
        response = self.client.get(self.url)
        assert response.status_code == 200
        # check another non-extension type also redirects
        self.addon.update(type=amo.ADDON_DICT)
        response = self.client.get(self.url)
        self.assert3xx(response, self.next_url)

    def test_cancel_button_present_listed(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.confirm-submission-cancel')[0].attrib['formaction'] == reverse(
            'devhub.addons.cancel', args=(self.addon.slug, 'listed')
        )

    def test_cancel_button_present_unlisted(self):
        self.addon.versions.update(channel=amo.CHANNEL_UNLISTED)
        self.url = reverse('devhub.submit.source', args=[self.addon.slug, 'unlisted'])
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.confirm-submission-cancel')[0].attrib['formaction'] == reverse(
            'devhub.addons.cancel', args=(self.addon.slug, 'unlisted')
        )


class DetailsPageMixin:
    """Some common methods between TestAddonSubmitDetails and
    TestStaticThemeSubmitDetails."""

    def is_success(self, data):
        assert self.get_addon().status == amo.STATUS_NULL
        response = self.client.post(self.url, data)
        assert all(self.get_addon().get_required_metadata())
        assert response.status_code == 302
        assert self.get_addon().status == amo.STATUS_NOMINATED
        return response

    def test_submit_name_existing(self):
        """Test that we can submit two add-ons with the same name."""
        qs = Addon.objects.filter(name__localized_string='Cooliris')
        assert qs.count() == 1
        self.is_success(self.get_dict(name='Cooliris'))
        assert qs.count() == 2

    def test_submit_name_length(self):
        # Make sure the name isn't too long.
        data = self.get_dict(name='a' * 51)
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        error = 'Ensure this value has at most 50 characters (it has 51).'
        self.assertFormError(response, 'describe_form', 'name', error)

    def test_submit_name_symbols_only(self):
        data = self.get_dict(name='()+([#')
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        error = 'Ensure this field contains at least one letter or number character.'
        self.assertFormError(response, 'describe_form', 'name', error)

        data = self.get_dict(name='±↡∋⌚')
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        error = 'Ensure this field contains at least one letter or number character.'
        self.assertFormError(response, 'describe_form', 'name', error)

        # 'ø' is not a symbol, it's actually a letter, so it should be valid.
        data = self.get_dict(name='ø')
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        assert self.get_addon().name == 'ø'

    def test_submit_slug_invalid(self):
        # Submit an invalid slug.
        data = self.get_dict(slug='slug!!! aksl23%%')
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        self.assertFormError(
            response,
            'describe_form',
            'slug',
            f'Enter a valid {STRING_QUOTE_OPEN}slug{STRING_QUOTE_CLOSE} consisting of '
            'letters, numbers, underscores or hyphens.',
        )

    def test_submit_slug_required(self):
        # Make sure the slug is required.
        response = self.client.post(self.url, self.get_dict(slug=''))
        assert response.status_code == 200
        self.assertFormError(
            response, 'describe_form', 'slug', 'This field is required.'
        )

    def test_submit_summary_required(self):
        # Make sure summary is required.
        response = self.client.post(self.url, self.get_dict(summary=''))
        assert response.status_code == 200
        self.assertFormError(
            response, 'describe_form', 'summary', 'This field is required.'
        )

    def test_submit_summary_symbols_only(self):
        data = self.get_dict(summary='()+([#')
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        error = 'Ensure this field contains at least one letter or number character.'
        self.assertFormError(response, 'describe_form', 'summary', error)

        data = self.get_dict(summary='±↡∋⌚')
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        error = 'Ensure this field contains at least one letter or number character.'
        self.assertFormError(response, 'describe_form', 'summary', error)

        # 'ø' is not a symbol, it's actually a letter, so it should be valid.
        data = self.get_dict(summary='ø')
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        assert self.get_addon().summary == 'ø'

    def test_submit_summary_length(self):
        # Summary is too long.
        response = self.client.post(self.url, self.get_dict(summary='a' * 251))
        assert response.status_code == 200
        error = 'Ensure this value has at most 250 characters (it has 251).'
        self.assertFormError(response, 'describe_form', 'summary', error)

    def test_due_date_set_only_once(self):
        AddonReviewerFlags.objects.create(
            addon=self.get_addon(), auto_approval_disabled=True
        )
        self.get_version().update(due_date=None, _signal=False)
        self.is_success(self.get_dict())
        self.assertCloseToNow(self.get_version().due_date, now=get_review_due_date())

        # Check due date is only set once, see bug 632191.
        duedate = datetime.now() - timedelta(days=5)
        self.get_version().update(due_date=duedate, _signal=False)
        # Update something else in the addon:
        self.get_addon().update(slug='foobar')
        assert (
            self.get_version().due_date.timetuple()[0:5] == (duedate.timetuple()[0:5])
        )

    def test_submit_details_unlisted_should_redirect(self):
        version = self.get_addon().versions.latest()
        version.update(channel=amo.CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        self.assert3xx(response, self.next_step)

    def test_can_cancel_review(self):
        addon = self.get_addon()
        addon.versions.latest().file.update(status=amo.STATUS_AWAITING_REVIEW)

        cancel_url = reverse('devhub.addons.cancel', args=['a3615', 'listed'])
        versions_url = reverse('devhub.addons.versions', args=['a3615'])
        response = self.client.post(cancel_url)
        self.assert3xx(response, versions_url)

        addon = self.get_addon()
        assert addon.status == amo.STATUS_NULL
        version = addon.versions.latest()
        assert version.file.status == amo.STATUS_DISABLED

    @override_switch('content-optimization', active=False)
    def test_name_summary_lengths_short(self):
        # check the separate name and summary labels, etc are served
        response = self.client.get(self.url)
        assert b'Name and Summary' not in response.content
        assert b'It will be shown in listings and searches' in response.content

        data = self.get_dict(name='a', summary='b')
        self.is_success(data)

    @override_switch('content-optimization', active=False)
    def test_name_summary_lengths_long(self):
        data = self.get_dict(name='a' * 50, summary='b' * 50)
        self.is_success(data)

    @override_switch('content-optimization', active=True)
    def test_name_summary_lengths_content_optimization(self):
        # check the combined name and summary label, etc are served
        response = self.client.get(self.url)
        assert b'Name and Summary' in response.content

        # name and summary are too short
        response = self.client.post(
            self.url, self.get_dict(name='a', summary='b', description='c' * 10)
        )
        assert self.get_addon().name != 'a'
        assert self.get_addon().summary != 'b'
        assert response.status_code == 200
        self.assertFormError(
            response,
            'describe_form',
            'name',
            'Ensure this value has at least 2 characters (it has 1).',
        )
        self.assertFormError(
            response,
            'describe_form',
            'summary',
            'Ensure this value has at least 2 characters (it has 1).',
        )

        # name and summary individually are okay, but together are too long
        response = self.client.post(
            self.url,
            self.get_dict(name='a' * 50, summary='b' * 50, description='c' * 10),
        )
        assert self.get_addon().name != 'a' * 50
        assert self.get_addon().summary != 'b' * 50
        assert response.status_code == 200
        self.assertFormError(
            response,
            'describe_form',
            'name',
            'Ensure name and summary combined are at most 70 characters '
            '(they have 100).',
        )

        # success: together name and summary are 70 characters.
        data = self.get_dict(name='a' * 2, summary='b' * 68, description='c' * 10)
        self.is_success(data)

    @override_switch('content-optimization', active=True)
    def test_summary_auto_cropping_content_optimization(self):
        # See test_forms.py::TestDescribeForm for some more variations.
        data = self.get_dict(minimal=False)
        data.pop('name')
        data.pop('summary')
        data.update(
            {
                'name_en-us': 'a' * 25,
                'name_fr': 'b' * 30,
                'summary_en-us': 'c' * 45,
                'summary_fr': 'd' * 45,  # 30 + 45 is > 70
            }
        )
        self.is_success(data)

        assert self.get_addon().name == 'a' * 25
        assert self.get_addon().summary == 'c' * 45

        with self.activate('fr'):
            assert self.get_addon().name == 'b' * 30
            assert self.get_addon().summary == 'd' * 40

    @override_switch('content-optimization', active=True)
    def test_name_auto_cropping_content_optimization(self):
        # See test_forms.py::TestDescribeForm for some more variations.
        data = self.get_dict(minimal=False)
        data.pop('name')
        data.pop('summary')
        data.update(
            {
                'name_en-us': 'a' * 67,
                'name_fr': 'b' * 69,
                'summary_en-us': 'c' * 2,
                'summary_fr': 'd' * 3,
            }
        )
        self.is_success(data)

        assert self.get_addon().name == 'a' * 67
        assert self.get_addon().summary == 'c' * 2

        with self.activate('fr'):
            assert self.get_addon().name == 'b' * 68
            assert self.get_addon().summary == 'd' * 2


class TestAddonSubmitDetails(DetailsPageMixin, TestSubmitBase):
    def setUp(self):
        super().setUp()
        self.url = reverse('devhub.submit.details', args=['a3615'])

        addon = self.get_addon()
        AddonCategory.objects.filter(
            addon=addon,
            category_id=CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
        ).delete()
        AddonCategory.objects.filter(
            addon=addon,
            category_id=CATEGORIES[amo.ADDON_EXTENSION]['social-communication'].id,
        ).delete()

        cat_form = self.client.get(self.url).context['cat_form']
        self.cat_initial = initial(cat_form)
        self.next_step = reverse('devhub.submit.finish', args=['a3615'])
        License.objects.create(builtin=3)

        addon.current_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        addon.update(status=amo.STATUS_NULL)
        assert self.get_addon().status == amo.STATUS_NULL

    def get_dict(self, minimal=True, **kw):
        result = {}
        describe_form = {
            'name': 'Test name',
            'slug': 'testname',
            'summary': 'Hello!',
            'is_experimental': True,
            'requires_payment': True,
        }
        if not minimal:
            describe_form.update(
                {
                    'description': 'its a description',
                    'support_url': 'http://stackoverflow.com',
                    'support_email': 'black@hole.org',
                }
            )
        cat_form = kw.pop('cat_initial', self.cat_initial)
        license_form = {'license-builtin': 3}
        policy_form = (
            {}
            if minimal
            else {'has_priv': True, 'privacy_policy': 'Ur data belongs to us now.'}
        )
        reviewer_form = {} if minimal else {'approval_notes': 'approove plz'}
        result.update(describe_form)
        result.update(cat_form)
        result.update(license_form)
        result.update(policy_form)
        result.update(reviewer_form)
        result.update(**kw)
        return result

    @override_switch('content-optimization', active=False)
    def test_submit_success_required(self):
        # Set/change the required fields only
        response = self.client.get(self.url)
        assert response.status_code == 200

        # Post and be redirected - trying to sneak
        # in fields that shouldn't be modified via this form.
        data = self.get_dict(homepage='foo.com', tags='whatevs, whatever')
        self.is_success(data)

        addon = self.get_addon()

        # This fields should not have been modified.
        assert addon.homepage != 'foo.com'
        assert len(addon.tags.values_list()) == 0

        # These are the fields that are expected to be edited here.
        assert addon.name == 'Test name'
        assert addon.slug == 'testname'
        assert addon.summary == 'Hello!'
        assert addon.is_experimental
        assert addon.requires_payment
        assert (
            addon.all_categories[0].id
            == CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id
        )

        # Test add-on log activity.
        log_items = ActivityLog.objects.for_addons(addon)
        assert not log_items.filter(
            action=amo.LOG.EDIT_PROPERTIES.id
        ), "Setting properties on submit needn't be logged."

    @override_switch('content-optimization', active=False)
    def test_submit_success_optional_fields(self):
        # Set/change the optional fields too
        # Post and be redirected
        data = self.get_dict(minimal=False)
        self.is_success(data)

        addon = self.get_addon()

        # These are the fields that are expected to be edited here.
        assert addon.description == 'its a description'
        assert addon.support_url == 'http://stackoverflow.com'
        assert addon.support_email == 'black@hole.org'
        assert addon.privacy_policy == 'Ur data belongs to us now.'
        assert addon.current_version.approval_notes == 'approove plz'

    @override_switch('content-optimization', active=True)
    def test_submit_success_required_with_content_optimization(self):
        # Set/change the required fields only
        response = self.client.get(self.url)
        assert response.status_code == 200

        # Post and be redirected - trying to sneak
        # in fields that shouldn't be modified via this form.
        data = self.get_dict(
            description='its a description',
            homepage='foo.com',
            tags='whatevs, whatever',
        )
        self.is_success(data)

        addon = self.get_addon()

        # This fields should not have been modified.
        assert addon.homepage != 'foo.com'
        assert len(addon.tags.values_list()) == 0

        # These are the fields that are expected to be edited here.
        assert addon.name == 'Test name'
        assert addon.slug == 'testname'
        assert addon.summary == 'Hello!'
        assert addon.description == 'its a description'
        assert addon.is_experimental
        assert addon.requires_payment
        assert (
            addon.all_categories[0].id
            == CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id
        )

        # Test add-on log activity.
        log_items = ActivityLog.objects.for_addons(addon)
        assert not log_items.filter(
            action=amo.LOG.EDIT_PROPERTIES.id
        ), "Setting properties on submit needn't be logged."

    @override_switch('content-optimization', active=True)
    def test_submit_success_optional_fields_with_content_optimization(self):
        # Set/change the optional fields too
        # Post and be redirected
        data = self.get_dict(minimal=False)
        self.is_success(data)

        addon = self.get_addon()

        # These are the fields that are expected to be edited here.
        assert addon.support_url == 'http://stackoverflow.com'
        assert addon.support_email == 'black@hole.org'
        assert addon.privacy_policy == 'Ur data belongs to us now.'
        assert addon.current_version.approval_notes == 'approove plz'

    def test_submit_categories_required(self):
        del self.cat_initial['categories']
        response = self.client.post(
            self.url, self.get_dict(cat_initial=self.cat_initial)
        )
        assert response.context['cat_form'].errors['categories'] == (
            ['This field is required.']
        )

    def test_submit_categories_max(self):
        assert amo.MAX_CATEGORIES == 3
        self.cat_initial['categories'] = [
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['social-communication'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['games-entertainment'].id,
        ]
        response = self.client.post(
            self.url, self.get_dict(cat_initial=self.cat_initial)
        )
        assert response.context['cat_form'].errors['categories'] == (
            ['You can have only 3 categories.']
        )

    def test_submit_categories_add(self):
        assert [cat.id for cat in self.get_addon().all_categories] == [
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id
        ]
        self.cat_initial['categories'] = [
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
        ]

        self.is_success(self.get_dict())

        addon_cats = [c.id for c in self.get_addon().all_categories]
        assert sorted(addon_cats) == [
            CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
        ]

    def test_submit_categories_addandremove(self):
        AddonCategory(
            addon=self.addon,
            category_id=CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
        ).save()
        assert sorted(cat.id for cat in self.get_addon().all_categories) == [
            CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
        ]

        self.cat_initial['categories'] = [
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['social-communication'].id,
        ]
        self.client.post(self.url, self.get_dict(cat_initial=self.cat_initial))
        category_ids_new = [c.id for c in self.get_addon().all_categories]
        assert sorted(category_ids_new) == [
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['social-communication'].id,
        ]

    def test_submit_categories_remove(self):
        AddonCategory(
            addon=self.addon,
            category_id=CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
        ).save()
        assert sorted(cat.id for cat in self.get_addon().all_categories) == [
            1,
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
        ]

        self.cat_initial['categories'] = [
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id
        ]
        self.client.post(self.url, self.get_dict(cat_initial=self.cat_initial))
        category_ids_new = [cat.id for cat in self.get_addon().all_categories]
        assert category_ids_new == [CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id]

    def test_ul_class_rendering_regression(self):
        """Test ul of license widget doesn't render `license` class.

        Regression test for:
         * https://github.com/mozilla/addons-server/issues/8902
         * https://github.com/mozilla/addons-server/issues/8920
        """

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        ul = doc('#id_license-builtin')

        assert ul.attr('class') is None

    def test_set_builtin_license_no_log(self):
        self.is_success(self.get_dict(**{'license-builtin': 3}))
        addon = self.get_addon()
        assert addon.status == amo.STATUS_NOMINATED
        assert addon.current_version.license.builtin == 3
        log_items = ActivityLog.objects.for_addons(self.get_addon())
        assert not log_items.filter(action=amo.LOG.CHANGE_LICENSE.id)

    def test_license_error(self):
        response = self.client.post(self.url, self.get_dict(**{'license-builtin': 4}))
        assert response.status_code == 200
        self.assertFormError(
            response,
            'license_form',
            'builtin',
            'Select a valid choice. 4 is not one of the available choices.',
        )

    def test_set_privacy_nomsg(self):
        """
        You should not get punished with a 500 for not writing your policy...
        but perhaps you should feel shame for lying to us.  This test does not
        test for shame.
        """
        self.get_addon().update(eula=None, privacy_policy=None)
        self.is_success(self.get_dict(has_priv=True))

    def test_source_submission_notes_not_shown_by_default(self):
        url = reverse('devhub.submit.source', args=[self.addon.slug, 'listed'])
        response = self.client.post(url, {'has_source': 'no'}, follow=True)

        assert response.status_code == 200

        doc = pq(response.content)
        assert 'Remember: ' not in doc('.source-submission-note').text()

    def test_source_submission_notes_shown(self):
        url = reverse('devhub.submit.source', args=[self.addon.slug, 'listed'])

        response = self.client.post(
            url,
            {
                'has_source': 'yes',
                'source': self.generate_source_zip(),
            },
            follow=True,
        )

        assert response.status_code == 200

        doc = pq(response.content)
        assert 'Remember: ' in doc('.source-submission-note').text()


class TestStaticThemeSubmitDetails(DetailsPageMixin, TestSubmitBase):
    def setUp(self):
        super().setUp()
        self.client.logout()
        self.client.force_login(self.user)
        self.user.update(last_login_ip='192.0.2.0.1')
        self.url = reverse('devhub.submit.details', args=['a3615'])

        addon = self.get_addon()
        AddonCategory.objects.filter(
            addon=addon,
            category_id=CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
        ).delete()
        AddonCategory.objects.filter(
            addon=addon, category_id=CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id
        ).delete()
        AddonCategory.objects.filter(
            addon=addon,
            category_id=CATEGORIES[amo.ADDON_EXTENSION]['social-communication'].id,
        ).delete()

        self.next_step = reverse('devhub.submit.finish', args=['a3615'])
        License.objects.create(builtin=11)

        addon.current_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        addon.update(status=amo.STATUS_NULL, type=amo.ADDON_STATICTHEME)
        assert self.get_addon().status == amo.STATUS_NULL

    def get_dict(self, minimal=True, **kw):
        result = {}
        describe_form = {'name': 'Test name', 'slug': 'testname', 'summary': 'Hello!'}
        if not minimal:
            describe_form.update(
                {
                    'support_url': 'http://stackoverflow.com',
                    'support_email': 'black@hole.org',
                }
            )
        cat_form = {'categories': [300]}
        license_form = {'license-builtin': 11}
        result.update(describe_form)
        result.update(cat_form)
        result.update(license_form)
        result.update(**kw)
        return result

    def test_submit_success_required(self):
        # Set/change the required fields only
        response = self.client.get(self.url)
        assert response.status_code == 200

        # Post and be redirected - trying to sneak
        # in fields that shouldn't be modified via this form.
        data = self.get_dict(homepage='foo.com', tags='whatevs, whatever')
        self.is_success(data)

        addon = self.get_addon()

        # This fields should not have been modified.
        assert addon.homepage != 'foo.com'
        assert len(addon.tags.values_list()) == 0

        # These are the fields that are expected to be edited here.
        assert addon.name == 'Test name'
        assert addon.slug == 'testname'
        assert addon.summary == 'Hello!'
        assert addon.all_categories[0].id == 300

        # Test add-on log activity.
        log_items = ActivityLog.objects.for_addons(addon)
        assert not log_items.filter(
            action=amo.LOG.EDIT_PROPERTIES.id
        ), "Setting properties on submit needn't be logged."

    def test_submit_success_optional_fields(self):
        # Set/change the optional fields too
        # Post and be redirected
        data = self.get_dict(minimal=False)
        self.is_success(data)

        addon = self.get_addon()

        # These are the fields that are expected to be edited here.
        assert addon.support_url == 'http://stackoverflow.com'
        assert addon.support_email == 'black@hole.org'

    def test_submit_categories_set(self):
        assert [cat.id for cat in self.get_addon().all_categories] == []
        self.is_success(self.get_dict(categories=[308]))

        addon_cats = [c.id for c in self.get_addon().all_categories]
        assert sorted(addon_cats) == [308]

    def test_submit_categories_change(self):
        AddonCategory(addon=self.addon, category_id=300).save()
        assert sorted(cat.id for cat in self.get_addon().all_categories) == [300]

        self.client.post(self.url, self.get_dict(categories=[308]))
        category_ids_new = [cat.id for cat in self.get_addon().all_categories]
        # Only ever one category for Static Themes
        assert category_ids_new == [308]

    def test_creative_commons_licenses(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        content = doc('.addon-submission-process')
        assert content('#cc-chooser')  # cc license wizard
        assert content('#theme-license')  # cc license result
        assert content('#id_license-builtin')  # license list
        # There should be one license - 11 we added in setUp - and no 'other'.
        assert len(content('input.license')) == 1
        assert content('input.license').attr('value') == '11'
        assert content('input.license').attr('data-name') == (
            LICENSES_BY_BUILTIN[11].name
        )

    def test_set_builtin_license_no_log(self):
        self.is_success(self.get_dict(**{'license-builtin': 11}))
        addon = self.get_addon()
        assert addon.status == amo.STATUS_NOMINATED
        assert addon.current_version.license.builtin == 11
        log_items = ActivityLog.objects.for_addons(self.get_addon())
        assert not log_items.filter(action=amo.LOG.CHANGE_LICENSE.id)

    def test_license_error(self):
        response = self.client.post(self.url, self.get_dict(**{'license-builtin': 4}))
        assert response.status_code == 200
        self.assertFormError(
            response,
            'license_form',
            'builtin',
            'Select a valid choice. 4 is not one of the available choices.',
        )


class TestAddonSubmitFinish(TestSubmitBase):
    def setUp(self):
        super().setUp()
        self.url = reverse('devhub.submit.finish', args=[self.addon.slug])

    def test_finish_submitting_listed_addon(self):
        version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 4
        # First link is to extensionworkshop
        assert links[0].attrib['href'].startswith(settings.EXTENSION_WORKSHOP_URL)
        # Then edit listing
        assert links[1].attrib['href'] == self.addon.get_dev_url()
        # Then to edit the version
        assert links[2].attrib['href'] == reverse(
            'devhub.versions.edit', args=[self.addon.slug, version.id]
        )
        assert links[2].text == ('Edit version %s' % version.version)
        # And finally back to my submissions.
        assert links[3].attrib['href'] == reverse('devhub.addons')

    def test_finish_submitting_unlisted_addon(self):
        self.make_addon_unlisted(self.addon)

        self.addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 1
        # Link leads back to my submissions.
        assert links[0].attrib['href'] == reverse('devhub.addons')

    def test_addon_no_versions_redirects_to_versions(self):
        self.addon.update(status=amo.STATUS_NULL)
        self.addon.versions.all().delete()
        response = self.client.get(self.url, follow=True)
        # Would go to 'devhub.submit.version' but no previous version means
        # channel needs to be selected first.
        self.assert3xx(
            response, reverse('devhub.submit.version.distribution', args=['a3615']), 302
        )

    def test_incomplete_directs_to_details(self):
        # We get bounced back to details step.
        self.addon.update(status=amo.STATUS_NULL)
        AddonCategory.objects.filter(addon=self.addon).delete()
        response = self.client.get(
            reverse('devhub.submit.finish', args=['a3615']), follow=True
        )
        self.assert3xx(response, reverse('devhub.submit.details', args=['a3615']))

    def test_finish_submitting_listed_static_theme(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        VersionPreview.objects.create(version=version)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 2
        # First link is to edit listing.
        assert links[0].attrib['href'] == self.addon.get_dev_url()
        # Second link is back to my submissions.
        assert links[1].attrib['href'] == reverse('devhub.themes')

        # Text is static theme specific.
        assert b'This version will be available after it passes review.' in (
            response.content
        )
        # Show the preview we started generating just after the upload step.
        imgs = content('section.addon-submission-process img')
        assert imgs[0].attrib['src'] == (version.previews.first().image_url)
        assert len(imgs) == 1  # Just the one preview though.

    def test_finish_submitting_unlisted_static_theme(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        self.make_addon_unlisted(self.addon)

        self.addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 1
        # Link leads back to my submissions.
        assert links[0].attrib['href'] == reverse('devhub.themes')


class TestAddonSubmitResume(TestSubmitBase):
    def test_redirect_from_other_pages(self):
        self.addon.update(status=amo.STATUS_NULL)
        AddonCategory.objects.filter(addon=self.addon).delete()
        response = self.client.get(
            reverse('devhub.addons.edit', args=['a3615']), follow=True
        )
        self.assert3xx(response, reverse('devhub.submit.details', args=['a3615']))


class TestVersionSubmitDistribution(TestSubmitBase):
    def setUp(self):
        super().setUp()
        self.url = reverse('devhub.submit.version.distribution', args=[self.addon.slug])

    def test_listed_redirects_to_next_step(self):
        response = self.client.post(self.url, {'channel': 'listed'})
        self.assert3xx(
            response,
            reverse('devhub.submit.version.upload', args=[self.addon.slug, 'listed']),
        )

    def test_unlisted_redirects_to_next_step(self):
        response = self.client.post(self.url, {'channel': 'unlisted'})
        self.assert3xx(
            response,
            reverse('devhub.submit.version.upload', args=[self.addon.slug, 'unlisted']),
        )

    def test_unlisted_redirects_to_next_step_if_addon_is_invisible(self):
        self.addon.update(disabled_by_user=True)
        response = self.client.post(self.url, {'channel': 'unlisted'})
        self.assert3xx(
            response,
            reverse('devhub.submit.version.upload', args=[self.addon.slug, 'unlisted']),
        )

    def test_listed_not_available_if_addon_is_invisible(self):
        self.addon.update(disabled_by_user=True)
        response = self.client.post(self.url, {'channel': 'listed'})
        # Not redirected, instead the page is shown with an error.
        assert response.status_code == 200
        doc = pq(response.content)
        errorlist = doc('.errorlist')
        assert errorlist.text().startswith('Select a valid choice.')

    def test_preselected_channel(self):
        response = self.client.get(self.url, {'channel': 'listed'})
        assert response.status_code == 200
        doc = pq(response.content)
        channel_input = doc('form.addon-submit-distribute input.channel')
        assert channel_input[0].attrib == {
            'type': 'radio',
            'name': 'channel',
            'value': 'listed',
            'class': 'channel',
            'required': '',
            'id': 'id_channel_0',
            'checked': 'checked',
        }
        assert channel_input[1].attrib == {
            'type': 'radio',
            'name': 'channel',
            'value': 'unlisted',
            'class': 'channel',
            'required': '',
            'id': 'id_channel_1',
        }
        # There should not be a warning, the add-on is not disabled.
        assert not doc('p.status-disabled')

    def test_no_preselected_channel_if_addon_is_invisible(self):
        # If add-on is "Invisible", the only choice available is "unlisted",
        # and there is no preselection (there is no point for the user to
        # land on this page in the first place, the link should be hidden).
        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url, {'channel': 'unlisted'})
        assert response.status_code == 200
        doc = pq(response.content)
        channel_input = doc('form.addon-submit-distribute input.channel')
        assert len(channel_input) == 1
        assert channel_input[0].attrib == {
            'type': 'radio',
            'name': 'channel',
            'value': 'unlisted',
            'class': 'channel',
            'required': '',
            'id': 'id_channel_0',
        }
        # There should be a warning.
        assert doc('p.status-disabled')

    def test_no_redirect_for_metadata(self):
        self.addon.update(status=amo.STATUS_NULL)
        AddonCategory.objects.filter(addon=self.addon).delete()
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_has_read_agreement(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(self.url)
        self.assert3xx(
            response, reverse('devhub.submit.version.agreement', args=[self.addon.slug])
        )

    def test_enforce_2fa(self):
        self.client.logout()
        self.client.force_login(self.user)
        self.user.update(last_login_ip='192.168.48.50')
        response = self.client.get(self.url)
        expected_location = fxa_login_url(
            config=settings.FXA_CONFIG['default'],
            state=self.client.session['fxa_state'],
            next_path=self.url,
            enforce_2fa=True,
            login_hint=self.user.email,
        )
        self.assert3xx(response, expected_location)

    def test_dont_enforce_2fa_for_static_theme(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        self.client.logout()
        self.client.force_login(self.user)
        self.user.update(last_login_ip='192.168.48.50')
        response = self.client.get(self.url)
        assert response.status_code == 200


class TestVersionSubmitAutoChannel(TestSubmitBase):
    """Just check we chose the right upload channel.  The upload tests
    themselves are in other tests."""

    def setUp(self):
        super().setUp()
        self.url = reverse('devhub.submit.version', args=[self.addon.slug])

    @mock.patch('olympia.devhub.views._submit_upload', side_effect=views._submit_upload)
    def test_listed_last_uses_listed_upload(self, _submit_upload_mock):
        version_factory(addon=self.addon, channel=amo.CHANNEL_LISTED)
        self.client.post(self.url)
        assert _submit_upload_mock.call_count == 1
        args, _ = _submit_upload_mock.call_args
        assert args[1:] == (
            self.addon,
            amo.CHANNEL_LISTED,
            'devhub.submit.version.source',
        )

    @mock.patch('olympia.devhub.views._submit_upload', side_effect=views._submit_upload)
    def test_unlisted_last_uses_unlisted_upload(self, _submit_upload_mock):
        version_factory(addon=self.addon, channel=amo.CHANNEL_UNLISTED)
        self.client.post(self.url)
        assert _submit_upload_mock.call_count == 1
        args, _ = _submit_upload_mock.call_args
        assert args[1:] == (
            self.addon,
            amo.CHANNEL_UNLISTED,
            'devhub.submit.version.source',
        )

    def test_no_versions_redirects_to_distribution(self):
        [v.delete() for v in self.addon.versions.all()]
        response = self.client.post(self.url)
        self.assert3xx(
            response,
            reverse('devhub.submit.version.distribution', args=[self.addon.slug]),
        )

    def test_has_read_agreement(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(self.url)
        self.assert3xx(
            response, reverse('devhub.submit.version.agreement', args=[self.addon.slug])
        )


class VersionSubmitUploadMixin:
    channel = None
    fixtures = ['base/users', 'base/addon_3615']

    @classmethod
    def setUpTestData(cls):
        create_default_webext_appversion()

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.addon.update(guid='@webextension-guid')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.client.force_login_with_2fa(self.user)
        self.user.update(last_login_ip='192.0.2.1')
        self.addon.versions.update(channel=self.channel, version='0.0.0.99')
        channel = 'listed' if self.channel == amo.CHANNEL_LISTED else 'unlisted'
        self.url = reverse(
            'devhub.submit.version.upload', args=[self.addon.slug, channel]
        )
        assert self.addon.has_complete_metadata()
        self.version.save()
        self.upload = self.get_upload('webextension.xpi', user=self.user)
        self.statsd_incr_mock = self.patch('olympia.devhub.views.statsd.incr')
        self.create_flag('2fa-enforcement-for-developers-and-special-users')

    def post(
        self,
        compatible_apps=None,
        override_validation=False,
        expected_status=302,
        source=None,
        extra_kwargs=None,
    ):
        if compatible_apps is None:
            compatible_apps = [amo.FIREFOX]
        data = {
            'upload': self.upload.uuid.hex,
            'compatible_apps': [p.id for p in compatible_apps],
            'admin_override_validation': override_validation,
        }
        if source is not None:
            data['source'] = source
        response = self.client.post(self.url, data, **(extra_kwargs or {}))
        assert response.status_code == expected_status
        return response

    def get_next_url(self, version):
        return reverse(
            'devhub.submit.version.source', args=[self.addon.slug, version.pk]
        )

    def test_missing_compatibility_apps(self):
        response = self.client.post(self.url, {'upload': self.upload.uuid.hex})
        assert response.status_code == 200
        assert response.context['new_addon_form'].errors.as_text() == (
            '* compatible_apps\n  * Need to select at least one application.'
        )

    def test_unique_version_num(self):
        self.version.update(version='0.0.1')
        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'Version 0.0.1 already exists.'
        )

    def test_same_version_if_previous_is_rejected(self):
        # We can't re-use the same version number, even if the previous
        # versions have been disabled/rejected.
        self.version.update(version='0.0.1')
        self.version.file.update(status=amo.STATUS_DISABLED)
        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'Version 0.0.1 already exists.'
        )

    def test_same_version_if_previous_is_deleted(self):
        # We can't re-use the same version number if the previous
        # versions has been deleted either.
        self.version.update(version='0.0.1')
        self.version.delete()
        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'Version 0.0.1 was uploaded before and deleted.'
        )

    def test_same_version_if_previous_is_awaiting_review(self):
        # We can't re-use the same version number - offer to continue.
        self.version.update(version='0.0.1')
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'Version 0.0.1 already exists. Continue with existing upload instead?'
        )
        # url is always to the details page even for unlisted (will redirect).
        assert pq(response.content)('ul.errorlist a').attr('href') == (
            reverse(
                'devhub.submit.version.details', args=[self.addon.slug, self.version.pk]
            )
        )

    def test_distribution_link(self):
        response = self.client.get(self.url)
        channel_text = 'listed' if self.channel == amo.CHANNEL_LISTED else 'unlisted'
        distribution_url = reverse(
            'devhub.submit.version.distribution', args=[self.addon.slug]
        )
        doc = pq(response.content)
        assert doc('.addon-submit-distribute a:contains("Change")').attr('href') == (
            distribution_url + '?channel=' + channel_text
        )
        assert not doc('p.status-disabled')

    def test_url_is_404_for_disabled_addons(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_no_redirect_for_metadata(self):
        self.addon.update(status=amo.STATUS_NULL)
        AddonCategory.objects.filter(addon=self.addon).delete()
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_static_theme_wizard_button_not_shown_for_extensions(self):
        assert self.addon.type != amo.ADDON_STATICTHEME
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#wizardlink')

    def test_static_theme_wizard_button_shown(self):
        channel = 'listed' if self.channel == amo.CHANNEL_LISTED else 'unlisted'
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#wizardlink')
        assert doc('#wizardlink').attr('href') == (
            reverse('devhub.submit.version.wizard', args=[self.addon.slug, channel])
        )

    def test_static_theme_wizard(self):
        channel = 'listed' if self.channel == amo.CHANNEL_LISTED else 'unlisted'
        self.addon.update(type=amo.ADDON_STATICTHEME)
        self.version.update(version='2.1')
        # Get the correct template.
        self.url = reverse(
            'devhub.submit.version.wizard', args=[self.addon.slug, channel]
        )
        mock_point = 'olympia.devhub.views.extract_theme_properties'
        with mock.patch(mock_point) as extract_theme_properties_mock:
            extract_theme_properties_mock.return_value = {
                'colors': {
                    'frame': '#123456',
                    'tab_background_text': 'rgba(1,2,3,0.4)',
                },
                'images': {
                    'theme_frame': 'header.png',
                },
            }
            response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#theme-wizard')
        assert doc('#theme-wizard').attr('data-version') == '3.0'
        assert doc('input#theme-name').attr('type') == 'hidden'
        assert doc('input#theme-name').attr('value') == (str(self.addon.name))
        # Existing colors should be the default values for the fields
        assert doc('#frame').attr('value') == '#123456'
        assert doc('#tab_background_text').attr('value') == 'rgba(1,2,3,0.4)'
        # And the theme header url is there for the JS to load
        assert doc('#theme-header').attr('data-existing-header') == ('header.png')
        # No warning about extra properties
        assert b'are unsupported in this wizard' not in response.content

        # And then check the upload works.
        path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip'
        )
        self.upload = self.get_upload(abspath=path, user=self.user)
        response = self.post()

        version = self.addon.find_latest_version(channel=self.channel)
        assert version.channel == self.channel
        assert version.file.status == amo.STATUS_AWAITING_REVIEW
        self.assert3xx(response, self.get_next_url(version))
        log_items = ActivityLog.objects.for_addons(self.addon)
        assert log_items.filter(action=amo.LOG.ADD_VERSION.id)
        if self.channel == amo.CHANNEL_LISTED:
            previews = list(version.previews.all())
            assert len(previews) == 2
            assert storage.exists(previews[0].image_path)
            assert storage.exists(previews[1].image_path)
        else:
            assert version.previews.all().count() == 0

    def test_static_theme_wizard_unsupported_properties(self):
        channel = 'listed' if self.channel == amo.CHANNEL_LISTED else 'unlisted'
        self.addon.update(type=amo.ADDON_STATICTHEME)
        self.version.update(version='2.1')
        # Get the correct template.
        self.url = reverse(
            'devhub.submit.version.wizard', args=[self.addon.slug, channel]
        )
        mock_point = 'olympia.devhub.views.extract_theme_properties'
        with mock.patch(mock_point) as extract_theme_properties_mock:
            extract_theme_properties_mock.return_value = {
                'colors': {
                    'frame': '#123456',
                    'tab_background_text': 'rgba(1,2,3,0.4)',
                    'icons': '#123',
                },
                'images': {
                    'additional_backgrounds': [],
                },
                'something_extra': {},
            }
            response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#theme-wizard')
        assert doc('#theme-wizard').attr('data-version') == '3.0'
        assert doc('input#theme-name').attr('type') == 'hidden'
        assert doc('input#theme-name').attr('value') == (str(self.addon.name))
        # Existing colors should be the default values for the fields
        assert doc('#frame').attr('value') == '#123456'
        assert doc('#tab_background_text').attr('value') == 'rgba(1,2,3,0.4)'
        # Warning about extra properties this time:
        assert b'are unsupported in this wizard' in response.content
        unsupported_list = doc('.notification-box.error ul.note li')
        assert unsupported_list.length == 3
        assert 'icons' in unsupported_list.text()
        assert 'additional_backgrounds' in unsupported_list.text()
        assert 'something_extra' in unsupported_list.text()

        # And then check the upload works.
        path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip'
        )
        self.upload = self.get_upload(abspath=path, user=self.user)
        response = self.post()

        version = self.addon.find_latest_version(channel=self.channel)
        assert version.channel == self.channel
        assert version.file.status == amo.STATUS_AWAITING_REVIEW
        self.assert3xx(response, self.get_next_url(version))
        log_items = ActivityLog.objects.for_addons(self.addon)
        assert log_items.filter(action=amo.LOG.ADD_VERSION.id)
        if self.channel == amo.CHANNEL_LISTED:
            previews = list(version.previews.all())
            assert len(previews) == 2
            assert storage.exists(previews[0].image_path)
            assert storage.exists(previews[1].image_path)
        else:
            assert version.previews.all().count() == 0

    def test_submit_notification_warning(self):
        config = Config.objects.create(
            key='submit_notification_warning',
            value='Text with <a href="http://example.com">a link</a>.',
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.notification-box.warning')
        assert doc('.notification-box.warning').html().strip() == config.value

    def test_submit_notification_warning_pre_review_ignore_if_not_promoted_group(self):
        Config.objects.create(
            key='submit_notification_warning_pre_review',
            value='Warning for pre_review and <a href="http://example.com">a link</a>.',
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('.notification-box.warning')

    def test_submit_notification_warning_pre_review(self):
        self.make_addon_promoted(self.addon, group=NOTABLE)
        config = Config.objects.create(
            key='submit_notification_warning_pre_review',
            value='Warning for pre_review and <a href="http://example.com">a link</a>.',
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.notification-box.warning')
        assert doc('.notification-box.warning').html().strip() == config.value

    def test_submit_notification_warning_pre_review_generic_test_already_present(self):
        self.make_addon_promoted(self.addon, group=NOTABLE)
        config = Config.objects.create(
            key='submit_notification_warning',
            value='Warning with <a href="http://example.com">a link</a>.',
        )
        Config.objects.create(
            key='submit_notification_warning_pre_review',
            value='Warning for pre_review and <a href="http://example.com">a link</a>.',
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.notification-box.warning')
        assert doc('.notification-box.warning').html().strip() == config.value

    def test_enforce_2fa(self):
        self.client.logout()
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        expected_location = fxa_login_url(
            config=settings.FXA_CONFIG['default'],
            state=self.client.session['fxa_state'],
            next_path=self.url,
            enforce_2fa=True,
            login_hint=self.user.email,
        )
        self.assert3xx(response, expected_location)

    def test_dont_enforce_2fa_for_static_theme(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        self.client.logout()
        self.client.force_login(self.user)
        self.user.update(last_login_ip='192.168.48.50')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#id_theme_specific').attr('value') == 'True'


class TestVersionSubmitUploadListed(VersionSubmitUploadMixin, UploadMixin, TestCase):
    channel = amo.CHANNEL_LISTED

    def test_success(self):
        response = self.post()
        version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        assert version.channel == amo.CHANNEL_LISTED
        assert version.file.status == amo.STATUS_AWAITING_REVIEW
        self.assert3xx(response, self.get_next_url(version))
        logs_qs = ActivityLog.objects.for_addons(self.addon).filter(
            action=amo.LOG.ADD_VERSION.id
        )
        assert logs_qs.count() == 1
        log = logs_qs.get()
        assert log.iplog.ip_address_binary == IPv4Address(self.upload.ip_address)
        self.statsd_incr_mock.assert_any_call('devhub.submission.version.listed')
        provenance = VersionProvenance.objects.get()
        assert provenance.version == version
        assert provenance.source == amo.UPLOAD_SOURCE_DEVHUB
        assert provenance.client_info is None

    def test_success_custom_user_agent(self):
        response = self.post(extra_kwargs={'HTTP_USER_AGENT': 'Whatever/1.2.3.4'})
        version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        assert version.channel == amo.CHANNEL_LISTED
        assert version.file.status == amo.STATUS_AWAITING_REVIEW
        self.assert3xx(response, self.get_next_url(version))
        logs_qs = ActivityLog.objects.for_addons(self.addon).filter(
            action=amo.LOG.ADD_VERSION.id
        )
        assert logs_qs.count() == 1
        log = logs_qs.get()
        assert log.iplog.ip_address_binary == IPv4Address(self.upload.ip_address)
        self.statsd_incr_mock.assert_any_call('devhub.submission.version.listed')
        provenance = VersionProvenance.objects.get()
        assert provenance.version == version
        assert provenance.source == amo.UPLOAD_SOURCE_DEVHUB
        assert provenance.client_info == 'Whatever/1.2.3.4'

    def test_experiment_inside_webext_upload_without_permission(self):
        self.upload = self.get_upload(
            'experiment_inside_webextension.xpi',
            validation=json.dumps(
                {
                    'notices': 2,
                    'errors': 0,
                    'messages': [],
                    'metadata': {},
                    'warnings': 1,
                }
            ),
            user=self.user,
        )
        self.addon.update(
            guid='@experiment-inside-webextension-guid', status=amo.STATUS_APPROVED
        )

        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'You cannot submit this type of add-on'
        )

    def test_theme_experiment_inside_webext_upload_without_permission(self):
        self.upload = self.get_upload(
            'theme_experiment_inside_webextension.xpi',
            validation=json.dumps(
                {
                    'notices': 2,
                    'errors': 0,
                    'messages': [],
                    'metadata': {},
                    'warnings': 1,
                }
            ),
            user=self.user,
        )
        self.addon.update(
            guid='@theme–experiment-inside-webextension-guid',
            status=amo.STATUS_APPROVED,
        )

        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'You cannot submit this type of add-on'
        )

    def test_incomplete_addon_now_nominated(self):
        """Uploading a new version for an incomplete addon should set it to
        nominated."""
        self.addon.current_version.file.update(status=amo.STATUS_DISABLED)
        self.addon.update_status()
        # Deleting all the versions should make it null.
        assert self.addon.status == amo.STATUS_NULL
        self.post()
        self.addon.reload()
        assert self.addon.status == amo.STATUS_NOMINATED

    def test_langpack_requires_permission(self):
        self.addon.update(guid='langpack-de@firefox.mozilla.org')
        AppVersion.objects.create(application=amo.FIREFOX.id, version='66.0a1')
        self.upload = self.get_upload(
            'webextension_langpack.xpi',
            validation=json.dumps(
                {
                    'notices': 2,
                    'errors': 0,
                    'messages': [],
                    'metadata': {},
                    'warnings': 1,
                }
            ),
            user=self.user,
        )

        self.addon.update(type=amo.ADDON_LPAPP)

        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'You cannot submit a language pack'
        )

        self.grant_permission(self.user, ':'.join(amo.permissions.LANGPACK_SUBMIT))

        response = self.post(expected_status=302)

        version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)

        self.assert3xx(
            response,
            reverse('devhub.submit.version.source', args=[self.addon.slug, version.pk]),
        )

    def test_redirect_if_addon_is_invisible(self):
        self.addon.update(disabled_by_user=True)
        # We should be redirected to the "distribution" page, because we tried
        # to access the listed upload page while the add-on was "invisible".
        response = self.client.get(self.url)
        self.assert3xx(
            response,
            reverse('devhub.submit.version.distribution', args=[self.addon.slug]),
            302,
        )

        # Same for posts.
        response = self.post(expected_status=302)
        self.assert3xx(
            response,
            reverse('devhub.submit.version.distribution', args=[self.addon.slug]),
            302,
        )

    def test_version_num_must_be_greater(self):
        self.version.update(version='0.0.2')
        self.version.file.update(is_signed=True)
        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'Version 0.0.1 must be greater than the previous approved version 0.0.2.'
        )

    def test_version_num_must_be_numerically_greater(self):
        self.version.update(version='0.0.1.0')
        self.version.file.update(is_signed=True)
        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'Version 0.0.1 must be greater than the previous approved version 0.0.1.0.'
        )

    def test_android_compatibility_modal(self):
        url = reverse('devhub.submit.version.upload', args=[self.addon.slug, 'listed'])
        modal_selector = '#modals #modal-confirm-android-compatibility.modal'
        response = self.client.get(url)
        doc = pq(response.content)
        assert doc(modal_selector)

        self.make_addon_promoted(self.addon, RECOMMENDED, approve_version=True)
        response = self.client.get(url)
        doc = pq(response.content)
        assert not doc(modal_selector)


class TestVersionSubmitUploadUnlisted(VersionSubmitUploadMixin, UploadMixin, TestCase):
    channel = amo.CHANNEL_UNLISTED

    def test_success(self):
        # No validation errors or warning.
        result = {
            'errors': 0,
            'warnings': 0,
            'notices': 2,
            'metadata': {},
            'messages': [],
        }
        self.upload = self.get_upload(
            'webextension.xpi',
            validation=json.dumps(result),
            user=self.user,
        )
        response = self.post()
        version = self.addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)
        assert version.channel == amo.CHANNEL_UNLISTED
        assert version.file.status == amo.STATUS_AWAITING_REVIEW
        self.assert3xx(response, self.get_next_url(version))
        self.statsd_incr_mock.assert_any_call('devhub.submission.version.unlisted')

    def test_show_warning_and_remove_change_link_if_addon_is_invisible(self):
        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        # Channel should be 'unlisted' with a warning shown, no choice about it
        # since the add-on is "invisible".
        assert doc('p.status-disabled')
        # The link to select another distribution channel should be absent.
        assert not doc('.addon-submit-distribute a:contains("Change")')


class TestVersionSubmitSource(TestAddonSubmitSource):
    def setUp(self):
        super().setUp()
        addon = self.get_addon()
        self.version = version_factory(
            addon=addon,
            channel=amo.CHANNEL_LISTED,
            license_id=addon.versions.latest().license_id,
        )
        self.url = reverse(
            'devhub.submit.version.source', args=[addon.slug, self.version.pk]
        )
        self.next_url = reverse(
            'devhub.submit.version.details', args=[addon.slug, self.version.pk]
        )
        assert not self.get_version().source


class TestVersionSubmitDetails(TestSubmitBase):
    def setUp(self):
        super().setUp()
        addon = self.get_addon()
        self.version = version_factory(
            addon=addon,
            channel=amo.CHANNEL_LISTED,
            license_id=addon.versions.latest().license_id,
        )
        self.url = reverse(
            'devhub.submit.version.details', args=[addon.slug, self.version.pk]
        )

    def test_submit_empty_is_okay(self):
        assert all(self.get_addon().get_required_metadata())
        response = self.client.get(self.url)
        assert response.status_code == 200

        response = self.client.post(self.url, {})
        self.assert3xx(
            response,
            reverse(
                'devhub.submit.version.finish', args=[self.addon.slug, self.version.pk]
            ),
        )

        assert not self.version.approval_notes
        assert not self.version.release_notes

    def test_submit_success(self):
        assert all(self.get_addon().get_required_metadata())
        response = self.client.get(self.url)
        assert response.status_code == 200

        # Post and be redirected - trying to sneak in a field that shouldn't
        # be modified when this is not the first listed version.
        data = {
            'approval_notes': 'approove plz',
            'release_notes': 'loadsa stuff',
            'name': 'foo',
        }
        response = self.client.post(self.url, data)
        self.assert3xx(
            response,
            reverse(
                'devhub.submit.version.finish', args=[self.addon.slug, self.version.pk]
            ),
        )

        # This field should not have been modified.
        assert self.get_addon().name != 'foo'

        self.version.reload()
        assert self.version.approval_notes == 'approove plz'
        assert self.version.release_notes == 'loadsa stuff'

    def test_submit_details_unlisted_should_redirect(self):
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        assert all(self.get_addon().get_required_metadata())
        response = self.client.get(self.url)
        self.assert3xx(
            response,
            reverse(
                'devhub.submit.version.finish', args=[self.addon.slug, self.version.pk]
            ),
        )

    def test_can_cancel_review(self):
        addon = self.get_addon()
        addon_status = addon.status
        addon.versions.latest().file.update(status=amo.STATUS_AWAITING_REVIEW)

        cancel_url = reverse('devhub.addons.cancel', args=['a3615', 'listed'])
        versions_url = reverse('devhub.addons.versions', args=['a3615'])
        response = self.client.post(cancel_url)
        self.assert3xx(response, versions_url)

        addon = self.get_addon()
        assert addon.status == addon_status  # No change.
        version = addon.versions.latest()
        assert version.file.status == amo.STATUS_DISABLED

    def test_public_addon_stays_public_even_if_had_missing_metadata(self):
        """Posting details for a new version for a public add-on that somehow
        had missing metadata despite being public shouldn't reset it to
        nominated."""
        # Create a built-in License we'll use later when posting.
        License.objects.create(builtin=3)

        # Remove license from existing versions, but make sure the addon is
        # still public, just lacking metadata now.
        self.addon.versions.update(license_id=None)
        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        assert not self.addon.has_complete_metadata()

        # Now, submit details for that new version, adding license. Since
        # metadata is missing, name, slug, summary and category are required to
        # be present.
        data = {
            'name': str(self.addon.name),
            'slug': self.addon.slug,
            'summary': str(self.addon.summary),
            'categories': [CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id, 1],
            'license-builtin': 3,
        }
        response = self.client.post(self.url, data)
        self.assert3xx(
            response,
            reverse(
                'devhub.submit.version.finish', args=[self.addon.slug, self.version.pk]
            ),
        )
        self.addon.reload()
        assert self.addon.has_complete_metadata()
        assert self.addon.status == amo.STATUS_APPROVED

    def test_submit_static_theme_should_redirect(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        assert all(self.get_addon().get_required_metadata())
        response = self.client.get(self.url)
        # No extra details for subsequent theme uploads so just redirect.
        self.assert3xx(
            response,
            reverse(
                'devhub.submit.version.finish', args=[self.addon.slug, self.version.pk]
            ),
        )


class TestVersionSubmitDetailsFirstListed(TestAddonSubmitDetails):
    """Testing the case of a listed version being submitted on an add-on that
    previously only had unlisted versions - so is missing metadata."""

    def setUp(self):
        super().setUp()
        self.addon.versions.update(channel=amo.CHANNEL_UNLISTED)
        self.version = version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.version.update(license=None)  # Addon needs to be missing data.
        self.addon.update(status=amo.STATUS_NULL)
        self.url = reverse(
            'devhub.submit.version.details', args=['a3615', self.version.pk]
        )
        self.next_step = reverse(
            'devhub.submit.version.finish', args=['a3615', self.version.pk]
        )


class TestVersionSubmitFinish(TestAddonSubmitFinish):
    def setUp(self):
        super().setUp()
        addon = self.get_addon()
        self.version = version_factory(
            addon=addon,
            channel=amo.CHANNEL_LISTED,
            license_id=addon.versions.latest().license_id,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.url = reverse(
            'devhub.submit.version.finish', args=[addon.slug, self.version.pk]
        )

    @mock.patch(
        'olympia.devhub.tasks.send_initial_submission_acknowledgement_email.delay'
    )
    def test_no_welcome_email(self, send_initial_submission_acknowledgement_email_mock):
        """No emails for version finish."""
        self.client.get(self.url)
        assert not send_initial_submission_acknowledgement_email_mock.called

    def test_finish_submitting_listed_addon(self):
        version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 3
        # First link is to edit listing
        assert links[0].attrib['href'] == self.addon.get_dev_url()
        # Then to edit the version
        assert links[1].attrib['href'] == reverse(
            'devhub.versions.edit', args=[self.addon.slug, version.id]
        )
        assert links[1].text == ('Edit version %s' % version.version)
        # And finally back to my submissions.
        assert links[2].attrib['href'] == reverse('devhub.addons')

    def test_addon_no_versions_redirects_to_versions(self):
        # No versions makes getting to this step difficult!
        pass

    # No emails for any of these cases so ignore them.
    def test_welcome_email_for_newbies(self):
        pass

    def test_welcome_email_first_listed_addon(self):
        pass

    def test_welcome_email_if_previous_addon_is_incomplete(self):
        pass

    def test_no_welcome_email_if_unlisted(self):
        pass
