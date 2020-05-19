# -*- coding: utf-8 -*-
import json
import os
import io
import stat
import tarfile
import zipfile

from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.core.files import temp
from django.core.files.storage import default_storage as storage
from django.test.utils import override_settings

from unittest import mock
import responses

from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import (
    Addon, AddonCategory, AddonReviewerFlags, Category)
from olympia.amo.tests import (
    TestCase, addon_factory, create_default_webext_appversion, formset,
    initial, user_factory, version_factory)
from olympia.amo.urlresolvers import reverse
from olympia.blocklist.models import Block
from olympia.constants.categories import CATEGORIES_BY_ID
from olympia.constants.licenses import LICENSES_BY_BUILTIN
from olympia.devhub import views
from olympia.files.tests.test_models import UploadTest
from olympia.files.utils import parse_addon
from olympia.users.models import IPNetworkUserRestriction, UserProfile
from olympia.versions.models import License, VersionPreview
from olympia.zadmin.models import Config, set_config


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
        super(TestSubmitBase, self).setUp()
        assert self.client.login(email='del@icio.us')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.user.update(last_login_ip='192.168.1.1')
        self.addon = self.get_addon()

    def get_addon(self):
        return Addon.objects.get(pk=3615)

    def get_version(self):
        return self.get_addon().versions.latest()

    def generate_source_zip(self, suffix='.zip', data=u'z' * (2 ** 21),
                            compression=zipfile.ZIP_DEFLATED):
        tdir = temp.gettempdir()
        source = temp.NamedTemporaryFile(suffix=suffix, dir=tdir)
        with zipfile.ZipFile(source, 'w', compression=compression) as zip_file:
            zip_file.writestr('foo', data)
        source.seek(0)
        return source

    def generate_source_tar(
            self, suffix='.tar.gz', data=b't' * (2 ** 21), mode=None):
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

    def generate_source_garbage(self, suffix='.zip', data=b'g' * (2 ** 21)):
        tdir = temp.gettempdir()
        source = temp.NamedTemporaryFile(suffix=suffix, dir=tdir)
        source.write(data)
        source.seek(0)
        return source


class TestAddonSubmitAgreementWithPostReviewEnabled(TestSubmitBase):
    def test_set_read_dev_agreement(self):
        response = self.client.post(reverse('devhub.submit.agreement'), {
            'distribution_agreement': 'on',
            'review_policy': 'on',
        })
        assert response.status_code == 302
        self.user.reload()
        self.assertCloseToNow(self.user.read_dev_agreement)

    def test_set_read_dev_agreement_error(self):
        set_config('last_dev_agreement_change_date', '2019-06-10 00:00')
        before_agreement_last_changed = (
            datetime(2019, 6, 10) - timedelta(days=1))
        self.user.update(read_dev_agreement=before_agreement_last_changed)
        response = self.client.post(reverse('devhub.submit.agreement'))
        assert response.status_code == 200
        assert 'agreement_form' in response.context
        form = response.context['agreement_form']
        assert form.is_valid() is False
        assert form.errors == {
            'distribution_agreement': [u'This field is required.'],
            'review_policy': [u'This field is required.'],
        }
        doc = pq(response.content)
        for id_ in form.errors.keys():
            selector = 'li input#id_%s + a + .errorlist' % id_
            assert doc(selector).text() == 'This field is required.'

    def test_read_dev_agreement_skip(self):
        set_config('last_dev_agreement_change_date', '2019-06-10 00:00')
        after_agreement_last_changed = (
            datetime(2019, 6, 10) + timedelta(days=1))
        self.user.update(read_dev_agreement=after_agreement_last_changed)
        response = self.client.get(reverse('devhub.submit.agreement'))
        self.assert3xx(response, reverse('devhub.submit.distribution'))

    @override_settings(DEV_AGREEMENT_CHANGE_FALLBACK=datetime(
        2019, 6, 10, 12, 00))
    def test_read_dev_agreement_fallback_with_config_set_to_future(self):
        set_config('last_dev_agreement_change_date', '2099-12-31 00:00')
        read_dev_date = datetime(2019, 6, 11)
        self.user.update(read_dev_agreement=read_dev_date)
        response = self.client.get(reverse('devhub.submit.agreement'))
        self.assert3xx(response, reverse('devhub.submit.distribution'))

    def test_read_dev_agreement_fallback_with_conf_future_and_not_agreed(self):
        set_config('last_dev_agreement_change_date', '2099-12-31 00:00')
        self.user.update(read_dev_agreement=None)
        response = self.client.get(reverse('devhub.submit.agreement'))
        assert response.status_code == 200
        assert 'agreement_form' in response.context

    @override_settings(DEV_AGREEMENT_CHANGE_FALLBACK=datetime(
        2019, 6, 10, 12, 00))
    def test_read_dev_agreement_invalid_date_agreed_post_fallback(self):
        set_config('last_dev_agreement_change_date', '2099-25-75 00:00')
        read_dev_date = datetime(2019, 6, 11)
        self.user.update(read_dev_agreement=read_dev_date)
        response = self.client.get(reverse('devhub.submit.agreement'))
        self.assert3xx(response, reverse('devhub.submit.distribution'))

    def test_read_dev_agreement_invalid_date_not_agreed_post_fallback(self):
        set_config('last_dev_agreement_change_date', '2099,31,12,0,0')
        self.user.update(read_dev_agreement=None)
        response = self.client.get(reverse('devhub.submit.agreement'))
        self.assertRaises(ValueError)
        assert response.status_code == 200
        assert 'agreement_form' in response.context

    def test_read_dev_agreement_no_date_configured_agreed_post_fallback(self):
        response = self.client.get(reverse('devhub.submit.agreement'))
        self.assert3xx(response, reverse('devhub.submit.distribution'))

    def test_read_dev_agreement_no_date_configured_not_agreed_post_fallb(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(reverse('devhub.submit.agreement'))
        assert response.status_code == 200
        assert 'agreement_form' in response.context

    def test_read_dev_agreement_captcha_inactive(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(reverse('devhub.submit.agreement'))
        assert response.status_code == 200
        form = response.context['agreement_form']
        assert 'recaptcha' not in form.fields

        doc = pq(response.content)
        assert doc('.g-recaptcha') == []

    @override_switch('developer-agreement-captcha', active=True)
    def test_read_dev_agreement_captcha_active_error(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(reverse('devhub.submit.agreement'))
        assert response.status_code == 200
        form = response.context['agreement_form']
        assert 'recaptcha' in form.fields

        response = self.client.post(reverse('devhub.submit.agreement'))

        # Captcha is properly rendered
        doc = pq(response.content)
        assert doc('.g-recaptcha')

        assert 'recaptcha' in response.context['agreement_form'].errors

    @override_switch('developer-agreement-captcha', active=True)
    def test_read_dev_agreement_captcha_active_success(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(reverse('devhub.submit.agreement'))
        assert response.status_code == 200
        form = response.context['agreement_form']
        assert 'recaptcha' in form.fields
        # Captcha is also properly rendered
        doc = pq(response.content)
        assert doc('.g-recaptcha')

        verify_data = urlencode({
            'secret': '',
            'remoteip': '127.0.0.1',
            'response': 'test',
        })

        responses.add(
            responses.GET,
            'https://www.google.com/recaptcha/api/siteverify?' + verify_data,
            json={'error-codes': [], 'success': True})

        response = self.client.post(reverse('devhub.submit.agreement'), data={
            'g-recaptcha-response': 'test',
            'distribution_agreement': 'on',
            'review_policy': 'on',
        })

        assert response.status_code == 302
        assert response['Location'] == reverse('devhub.submit.distribution')

    def test_cant_submit_agreement_if_restricted_functional(self):
        IPNetworkUserRestriction.objects.create(network='127.0.0.1/32')
        self.user.update(read_dev_agreement=None)
        response = self.client.post(reverse('devhub.submit.agreement'), data={
            'distribution_agreement': 'on',
            'review_policy': 'on',
        })
        assert response.status_code == 200
        assert response.context['agreement_form'].is_valid() is False
        doc = pq(response.content)
        assert doc('.addon-submission-process').text().endswith(
            'Multiple add-ons violating our policies have been submitted '
            'from your location. The IP address has been blocked.\n'
            'More information on Developer Accounts'
        )

    def test_display_name_already_set_not_asked_again(self):
        self.user.update(read_dev_agreement=None, display_name='Foo')
        response = self.client.get(reverse('devhub.submit.agreement'))
        assert response.status_code == 200
        form = response.context['agreement_form']
        assert 'display_name' not in form.fields
        response = self.client.post(reverse('devhub.submit.agreement'), data={
            'distribution_agreement': 'on',
            'review_policy': 'on',
        })
        assert response.status_code == 302
        assert self.user.reload().read_dev_agreement

    def test_display_name_required(self):
        self.user.update(read_dev_agreement=None, display_name='')
        response = self.client.get(reverse('devhub.submit.agreement'))
        assert response.status_code == 200
        doc = pq(response.content)
        form = response.context['agreement_form']
        assert 'display_name' in form.fields
        assert 'Your account needs a display name' in doc(
            '.addon-submission-process').text()
        response = self.client.post(reverse('devhub.submit.agreement'), data={
            'distribution_agreement': 'on',
            'review_policy': 'on',
        })
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
        response = self.client.post(reverse('devhub.submit.agreement'), data={
            'distribution_agreement': 'on',
            'review_policy': 'on',
            'display_name': 'ö',  # Too short.
        })
        assert response.status_code == 200
        assert response.context['agreement_form'].is_valid() is False
        assert response.context['agreement_form'].errors == {
            'display_name': [
                'Ensure this value has at least 2 characters (it has 1).'
            ]
        }

        response = self.client.post(reverse('devhub.submit.agreement'), data={
            'distribution_agreement': 'on',
            'review_policy': 'on',
            'display_name': '\n\n\n',  # Only contains non-printable chars
        })
        assert response.status_code == 200
        assert response.context['agreement_form'].is_valid() is False
        assert response.context['agreement_form'].errors == {
            'display_name': ['This field is required.']
        }

        response = self.client.post(reverse('devhub.submit.agreement'), data={
            'distribution_agreement': 'on',
            'review_policy': 'on',
            'display_name': 'Fôä',
        })
        assert response.status_code == 302
        self.user.reload()
        self.assertCloseToNow(self.user.read_dev_agreement)
        assert self.user.display_name == 'Fôä'


class TestAddonSubmitDistribution(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestAddonSubmitDistribution, self).setUp()
        self.client.login(email='regular@mozilla.com')
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.user.update(last_login_ip='192.168.1.1')

    def test_check_agreement_okay(self):
        response = self.client.post(reverse('devhub.submit.agreement'))
        self.assert3xx(response, reverse('devhub.submit.distribution'))
        response = self.client.get(reverse('devhub.submit.distribution'))
        assert response.status_code == 200
        # No error shown for a redirect from previous step.
        assert b'This field is required' not in response.content

    def test_submit_notification_warning(self):
        config = Config.objects.create(
            key='submit_notification_warning',
            value='Text with <a href="http://example.com">a link</a>.')
        response = self.client.get(reverse('devhub.submit.distribution'))
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.notification-box.warning').html().strip() == config.value

    def test_redirect_back_to_agreement(self):
        self.user.update(read_dev_agreement=None)

        response = self.client.get(
            reverse('devhub.submit.distribution'), follow=True)
        self.assert3xx(response, reverse('devhub.submit.agreement'))

        # read_dev_agreement needs to be a more recent date than
        # the setting.
        set_config('last_dev_agreement_change_date', '2019-06-10 00:00')
        before_agreement_last_changed = (
            datetime(2019, 6, 10) - timedelta(days=1))
        self.user.update(read_dev_agreement=before_agreement_last_changed)
        response = self.client.get(
            reverse('devhub.submit.distribution'), follow=True)
        self.assert3xx(response, reverse('devhub.submit.agreement'))

    def test_redirect_back_to_agreement_if_restricted(self):
        IPNetworkUserRestriction.objects.create(network='127.0.0.1/32')
        response = self.client.get(
            reverse('devhub.submit.distribution'), follow=True)
        self.assert3xx(response, reverse('devhub.submit.agreement'))

    def test_listed_redirects_to_next_step(self):
        response = self.client.post(reverse('devhub.submit.distribution'),
                                    {'channel': 'listed'})
        self.assert3xx(response,
                       reverse('devhub.submit.upload', args=['listed']))

    def test_unlisted_redirects_to_next_step(self):
        response = self.client.post(reverse('devhub.submit.distribution'),
                                    {'channel': 'unlisted'})
        self.assert3xx(response, reverse('devhub.submit.upload',
                                         args=['unlisted']))

    def test_channel_selection_error_shown(self):
        url = reverse('devhub.submit.distribution')
        # First load should have no error
        assert b'This field is required' not in self.client.get(url).content

        # Load with channel preselected (e.g. back from next step) - no error.
        assert b'This field is required' not in self.client.get(
            url, args=['listed']).content

        # A post submission without channel selection should be an error
        assert b'This field is required' in self.client.post(url).content


@override_settings(REPUTATION_SERVICE_URL=None)
class TestAddonSubmitUpload(UploadTest, TestCase):
    fixtures = ['base/users']

    @classmethod
    def setUpTestData(cls):
        create_default_webext_appversion()

    def setUp(self):
        super(TestAddonSubmitUpload, self).setUp()
        self.upload = self.get_upload('webextension_no_id.xpi')
        assert self.client.login(email='regular@mozilla.com')
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.user.update(last_login_ip='192.168.1.1')
        self.client.post(reverse('devhub.submit.agreement'))

    def post(self, compatible_apps=None, expect_errors=False,
             listed=True, status_code=200, url=None, extra_kwargs=None):
        if compatible_apps is None:
            compatible_apps = [amo.FIREFOX, amo.ANDROID]
        data = {
            'upload': self.upload.uuid.hex,
            'compatible_apps': [p.id for p in compatible_apps]
        }
        url = url or reverse('devhub.submit.upload',
                             args=['listed' if listed else 'unlisted'])
        response = self.client.post(
            url, data, follow=True, **(extra_kwargs or {}))
        assert response.status_code == status_code
        if not expect_errors:
            # Show any unexpected form errors.
            if response.context and 'new_addon_form' in response.context:
                assert (
                    response.context['new_addon_form'].errors.as_text() == '')
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
        REPUTATION_SERVICE_TOKEN='some_token')
    def test_redirect_back_to_agreement_if_restricted_by_reputation(self):
        assert Addon.objects.count() == 0
        responses.add(
            responses.GET, 'https://reputation.example.com/type/ip/127.0.0.1',
            content_type='application/json',
            json={'reputation': 45})
        responses.add(
            responses.GET,
            'https://reputation.example.com/type/email/regular@mozilla.com',
            content_type='application/json',
            status=404)
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
        addon_factory(name='Beastify',
                      version_kw={'channel': amo.RELEASE_CHANNEL_LISTED})
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
        response = self.post()
        # Kind of redundant with the `self.post()` above: we just want to make
        # really sure there's no errors raised by posting an add-on with a name
        # that is already used by an unlisted add-on.
        assert 'new_addon_form' not in response.context
        assert get_addon_count('Beastify') == 2

    def test_new_addon_is_already_blocked(self):
        self.upload = self.get_upload('webextension.xpi')
        guid = '@webextension-guid'
        block = Block.objects.create(
            guid=guid, updated_by=user_factory())

        response = self.post(expect_errors=True)
        assert pq(response.content)('ul.errorlist').text() == (
            'Version 0.0.1 matches a blocklist entry for this add-on. '
            'You can contact AMO Admins for additional information.')
        assert pq(response.content)('ul.errorlist a').attr('href') == (
            reverse('blocklist.block', args=[guid]))

        # Though we allow if the version is outside of the specified range
        block.update(min_version='0.0.2')
        response = self.post(expect_errors=False)

    def test_success_listed(self):
        assert Addon.objects.count() == 0
        response = self.post()
        addon = Addon.objects.get()
        version = addon.find_latest_version(channel=amo.RELEASE_CHANNEL_LISTED)
        assert version
        assert version.channel == amo.RELEASE_CHANNEL_LISTED
        self.assert3xx(
            response, reverse('devhub.submit.source', args=[addon.slug]))
        log_items = ActivityLog.objects.for_addons(addon)
        assert log_items.filter(action=amo.LOG.CREATE_ADDON.id), (
            'New add-on creation never logged.')
        assert not addon.tags.filter(tag_text='dynamic theme').exists()

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
            'extension.xpi', validation=json.dumps(result))
        self.post(listed=False)
        addon = Addon.objects.get()
        version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert version
        assert version.files.all()[0].status == amo.STATUS_AWAITING_REVIEW
        assert version.channel == amo.RELEASE_CHANNEL_UNLISTED
        assert addon.status == amo.STATUS_NULL
        assert not addon.tags.filter(tag_text='dynamic theme').exists()

    def test_missing_compatible_apps(self):
        url = reverse('devhub.submit.upload', args=['listed'])
        response = self.client.post(url, {'upload': self.upload.uuid.hex})
        assert response.status_code == 200
        assert response.context['new_addon_form'].errors.as_text() == (
            '* compatible_apps\n  * Need to select at least one application.')
        doc = pq(response.content)
        assert doc('ul.errorlist').text() == (
            'Need to select at least one application.')

    def test_default_supported_platforms(self):
        """Test that we default to PLATFORM_ALL during submission.

        This is temporarily while we're in process of getting rid
        of supported platforms.

        https://github.com/mozilla/addons-server/issues/8752
        """
        response = self.post()
        addon = Addon.objects.get()
        # Success, redirecting to source submission step.
        self.assert3xx(
            response, reverse('devhub.submit.source', args=[addon.slug]))

        # Check that `all_files` is correct
        all_ = sorted([f.filename for f in addon.current_version.all_files])
        assert all_ == [u'beastify-1.0-an+fx.xpi']

        # Default to PLATFORM_ALL
        assert addon.current_version.supported_platforms == [amo.PLATFORM_ALL]

        # And check that compatible apps have a sensible default too
        apps = [app.id for app in addon.current_version.compatible_apps.keys()]
        assert sorted(apps) == sorted([amo.FIREFOX.id, amo.ANDROID.id])

    def test_static_theme_wizard_button_shown(self):
        response = self.client.get(reverse(
            'devhub.submit.upload', args=['listed']), follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#wizardlink')
        assert doc('#wizardlink').attr('href') == (
            reverse('devhub.submit.wizard', args=['listed']))

        response = self.client.get(reverse(
            'devhub.submit.upload', args=['unlisted']), follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#wizardlink')
        assert doc('#wizardlink').attr('href') == (
            reverse('devhub.submit.wizard', args=['unlisted']))

    def test_static_theme_submit_listed(self):
        assert Addon.objects.count() == 0
        path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip')
        self.upload = self.get_upload(abspath=path)
        response = self.post()
        addon = Addon.objects.get()
        self.assert3xx(
            response, reverse('devhub.submit.details', args=[addon.slug]))
        all_ = sorted([f.filename for f in addon.current_version.all_files])
        assert all_ == [u'weta_fade-1.0-an+fx.xpi']  # A single XPI for all.
        assert addon.type == amo.ADDON_STATICTHEME
        previews = list(addon.current_version.previews.all())
        assert len(previews) == 3
        assert storage.exists(previews[0].image_path)
        assert storage.exists(previews[1].image_path)
        assert storage.exists(previews[2].image_path)

    def test_static_theme_submit_unlisted(self):
        assert Addon.unfiltered.count() == 0
        path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip')
        self.upload = self.get_upload(abspath=path)
        response = self.post(listed=False)
        addon = Addon.unfiltered.get()
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.assert3xx(
            response, reverse('devhub.submit.finish', args=[addon.slug]))
        all_ = sorted([f.filename for f in latest_version.all_files])
        assert all_ == [u'weta_fade-1.0-an+fx.xpi']  # A single XPI for all.
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
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip')
        self.upload = self.get_upload(abspath=path)
        response = self.post(url=url)
        addon = Addon.objects.get()
        # Next step is same as non-wizard flow too.
        self.assert3xx(
            response, reverse('devhub.submit.details', args=[addon.slug]))
        all_ = sorted([f.filename for f in addon.current_version.all_files])
        assert all_ == [u'weta_fade-1.0-an+fx.xpi']  # A single XPI for all.
        assert addon.type == amo.ADDON_STATICTHEME
        previews = list(addon.current_version.previews.all())
        assert len(previews) == 3
        assert storage.exists(previews[0].image_path)
        assert storage.exists(previews[1].image_path)
        assert storage.exists(previews[2].image_path)

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
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip')
        self.upload = self.get_upload(abspath=path)
        response = self.post(url=url, listed=False)
        addon = Addon.unfiltered.get()
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        # Next step is same as non-wizard flow too.
        self.assert3xx(
            response, reverse('devhub.submit.finish', args=[addon.slug]))
        all_ = sorted([f.filename for f in latest_version.all_files])
        assert all_ == [u'weta_fade-1.0-an+fx.xpi']  # A single XPI for all.
        assert addon.type == amo.ADDON_STATICTHEME
        # Only listed submissions need a preview generated.
        assert latest_version.previews.all().count() == 0

    @mock.patch('olympia.devhub.forms.parse_addon',
                wraps=_parse_addon_theme_permission_wrapper)
    def test_listed_dynamic_theme_is_tagged(self, parse_addon_mock):
        assert Addon.objects.count() == 0
        path = os.path.join(
            settings.ROOT,
            'src/olympia/devhub/tests/addons/valid_webextension.xpi')
        self.upload = self.get_upload(abspath=path)
        response = self.post()
        addon = Addon.objects.get()
        self.assert3xx(
            response, reverse('devhub.submit.source', args=[addon.slug]))
        assert addon.tags.filter(tag_text='dynamic theme').exists()

    @mock.patch('olympia.devhub.forms.parse_addon',
                wraps=_parse_addon_theme_permission_wrapper)
    def test_unlisted_dynamic_theme_isnt_tagged(self, parse_addon_mock):
        assert Addon.objects.count() == 0
        path = os.path.join(
            settings.ROOT,
            'src/olympia/devhub/tests/addons/valid_webextension.xpi')
        self.upload = self.get_upload(abspath=path)
        response = self.post(listed=False)
        addon = Addon.objects.get()
        self.assert3xx(
            response, reverse('devhub.submit.source', args=[addon.slug]))
        assert not addon.tags.filter(tag_text='dynamic theme').exists()


class TestAddonSubmitSource(TestSubmitBase):

    def setUp(self):
        super(TestAddonSubmitSource, self).setUp()
        assert not self.get_version().source
        self.url = reverse('devhub.submit.source', args=[self.addon.slug])
        self.next_url = reverse(
            'devhub.submit.details', args=[self.addon.slug])

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
            if response.context and 'form' in response.context:
                assert response.context['form'].errors == {}
        return response

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=1)
    def test_submit_source(self):
        response = self.post(
            has_source=True, source=self.generate_source_zip())
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert self.get_version().source
        assert self.addon.needs_admin_code_review
        mode = (
            '0%o' % (os.stat(self.get_version().source.path)[stat.ST_MODE]))
        assert mode == '0100644'

    def test_submit_source_targz(self):
        response = self.post(
            has_source=True, source=self.generate_source_tar())
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert self.get_version().source
        assert self.addon.needs_admin_code_review
        mode = (
            '0%o' % (os.stat(self.get_version().source.path)[stat.ST_MODE]))
        assert mode == '0100644'

    def test_submit_source_tgz(self):
        response = self.post(
            has_source=True, source=self.generate_source_tar(
                suffix='.tgz'))
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert self.get_version().source
        assert self.addon.needs_admin_code_review
        mode = (
            '0%o' % (os.stat(self.get_version().source.path)[stat.ST_MODE]))
        assert mode == '0100644'

    def test_submit_source_tarbz2(self):
        response = self.post(
            has_source=True, source=self.generate_source_tar(
                suffix='.tar.bz2'))
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert self.get_version().source
        assert self.addon.needs_admin_code_review
        mode = (
            '0%o' % (os.stat(self.get_version().source.path)[stat.ST_MODE]))
        assert mode == '0100644'

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=1)
    def test_say_no_but_submit_source_anyway_fails(self):
        response = self.post(
            has_source=False, source=self.generate_source_zip(),
            expect_errors=True)
        assert response.context['form'].errors == {
            'source': [
                u'Source file uploaded but you indicated no source was needed.'
            ]
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source
        assert not self.addon.needs_admin_code_review

    def test_say_yes_but_dont_submit_source_fails(self):
        response = self.post(
            has_source=True, source=None, expect_errors=True)
        assert response.context['form'].errors == {
            'source': [u'You have not uploaded a source file.']
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source
        assert not self.addon.needs_admin_code_review

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=2 ** 22)
    def test_submit_source_in_memory_upload(self):
        source = self.generate_source_zip()
        source_size = os.stat(source.name)[stat.ST_SIZE]
        assert source_size < settings.FILE_UPLOAD_MAX_MEMORY_SIZE
        response = self.post(has_source=True, source=source)
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert self.get_version().source
        assert self.addon.needs_admin_code_review
        mode = (
            '0%o' % (os.stat(self.get_version().source.path)[stat.ST_MODE]))
        assert mode == '0100644'

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=2 ** 22)
    def test_submit_source_in_memory_upload_with_targz(self):
        source = self.generate_source_tar()
        source_size = os.stat(source.name)[stat.ST_SIZE]
        assert source_size < settings.FILE_UPLOAD_MAX_MEMORY_SIZE
        response = self.post(has_source=True, source=source)
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert self.get_version().source
        assert self.addon.needs_admin_code_review
        mode = (
            '0%o' % (os.stat(self.get_version().source.path)[stat.ST_MODE]))
        assert mode == '0100644'

    def test_with_bad_source_extension(self):
        response = self.post(
            has_source=True, source=self.generate_source_zip(suffix='.exe'),
            expect_errors=True)
        assert response.context['form'].errors == {
            'source': [
                u'Unsupported file type, please upload an archive file '
                u'(.zip, .tar.gz, .tar.bz2).'],
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source
        assert not self.addon.needs_admin_code_review

    def test_with_non_compressed_tar(self):
        response = self.post(
            # Generate a .tar.gz which is actually not compressed.
            has_source=True, source=self.generate_source_tar(mode='w'),
            expect_errors=True)
        assert response.context['form'].errors == {
            'source': [u'Invalid or broken archive.'],
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source
        assert not self.addon.needs_admin_code_review

    def test_with_bad_source_not_an_actual_archive(self):
        response = self.post(
            has_source=True, source=self.generate_source_garbage(
                suffix='.zip'), expect_errors=True)
        assert response.context['form'].errors == {
            'source': [u'Invalid or broken archive.'],
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source
        assert not self.addon.needs_admin_code_review

    def test_with_bad_source_broken_archive(self):
        source = self.generate_source_zip(
            data='Hello World', compression=zipfile.ZIP_STORED)
        data = source.read().replace(b'Hello World', b'dlroW olleH')
        source.seek(0)  # First seek to rewrite from the beginning
        source.write(data)
        source.seek(0)  # Second seek to reset like it's fresh.
        # Still looks like a zip at first glance.
        assert zipfile.is_zipfile(source)
        source.seek(0)  # Last seek to reset source descriptor before posting.
        response = self.post(
            has_source=True, source=source, expect_errors=True)
        assert response.context['form'].errors == {
            'source': [u'Invalid or broken archive.'],
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source
        assert not self.addon.needs_admin_code_review

    def test_with_bad_source_broken_archive_compressed_tar(self):
        source = self.generate_source_tar()
        with open(source.name, "r+b") as fobj:
            fobj.truncate(512)
        # Still looks like a tar at first glance.
        assert tarfile.is_tarfile(source.name)
        # Re-open and post.
        with open(source.name, 'rb'):
            response = self.post(
                has_source=True, source=source, expect_errors=True)
        assert response.context['form'].errors == {
            'source': [u'Invalid or broken archive.'],
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source
        assert not self.addon.needs_admin_code_review

    def test_no_source(self):
        response = self.post(has_source=False, source=None)
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert not self.get_version().source
        assert not self.addon.needs_admin_code_review

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


class DetailsPageMixin(object):
    """ Some common methods between TestAddonSubmitDetails and
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
        self.assertFormError(response, 'form', 'name', error)

    def test_submit_name_symbols_only(self):
        data = self.get_dict(name='()+([#')
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        error = (
            'Ensure this field contains at least one letter or number'
            ' character.')
        self.assertFormError(response, 'form', 'name', error)

        data = self.get_dict(name='±↡∋⌚')
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        error = (
            'Ensure this field contains at least one letter or number'
            ' character.')
        self.assertFormError(response, 'form', 'name', error)

        # 'ø' is not a symbol, it's actually a letter, so it should be valid.
        data = self.get_dict(name=u'ø')
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        assert self.get_addon().name == u'ø'

    def test_submit_slug_invalid(self):
        # Submit an invalid slug.
        data = self.get_dict(slug='slug!!! aksl23%%')
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        self.assertFormError(response, 'form', 'slug', "Enter a valid 'slug'" +
                             ' consisting of letters, numbers, underscores or '
                             'hyphens.')

    def test_submit_slug_required(self):
        # Make sure the slug is required.
        response = self.client.post(self.url, self.get_dict(slug=''))
        assert response.status_code == 200
        self.assertFormError(
            response, 'form', 'slug', 'This field is required.')

    def test_submit_summary_required(self):
        # Make sure summary is required.
        response = self.client.post(self.url, self.get_dict(summary=''))
        assert response.status_code == 200
        self.assertFormError(
            response, 'form', 'summary', 'This field is required.')

    def test_submit_summary_symbols_only(self):
        data = self.get_dict(summary='()+([#')
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        error = (
            'Ensure this field contains at least one letter or number'
            ' character.')
        self.assertFormError(response, 'form', 'summary', error)

        data = self.get_dict(summary='±↡∋⌚')
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        error = (
            'Ensure this field contains at least one letter or number'
            ' character.')
        self.assertFormError(response, 'form', 'summary', error)

        # 'ø' is not a symbol, it's actually a letter, so it should be valid.
        data = self.get_dict(summary=u'ø')
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        assert self.get_addon().summary == u'ø'

    def test_submit_summary_length(self):
        # Summary is too long.
        response = self.client.post(self.url, self.get_dict(summary='a' * 251))
        assert response.status_code == 200
        error = 'Ensure this value has at most 250 characters (it has 251).'
        self.assertFormError(response, 'form', 'summary', error)

    def test_nomination_date_set_only_once(self):
        self.get_version().update(nomination=None)
        self.is_success(self.get_dict())
        self.assertCloseToNow(self.get_version().nomination)

        # Check nomination date is only set once, see bug 632191.
        nomdate = datetime.now() - timedelta(days=5)
        self.get_version().update(nomination=nomdate, _signal=False)
        # Update something else in the addon:
        self.get_addon().update(slug='foobar')
        assert self.get_version().nomination.timetuple()[0:5] == (
            nomdate.timetuple()[0:5])

    def test_submit_details_unlisted_should_redirect(self):
        version = self.get_addon().versions.latest()
        version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        self.assert3xx(response, self.next_step)

    def test_can_cancel_review(self):
        addon = self.get_addon()
        addon.versions.latest().files.update(status=amo.STATUS_AWAITING_REVIEW)

        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        versions_url = reverse('devhub.addons.versions', args=['a3615'])
        response = self.client.post(cancel_url)
        self.assert3xx(response, versions_url)

        addon = self.get_addon()
        assert addon.status == amo.STATUS_NULL
        version = addon.versions.latest()
        del version.all_files
        assert version.statuses == [
            (version.all_files[0].id, amo.STATUS_DISABLED)]

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
            self.url, self.get_dict(
                name='a', summary='b', description='c' * 10))
        assert self.get_addon().name != 'a'
        assert self.get_addon().summary != 'b'
        assert response.status_code == 200
        self.assertFormError(
            response, 'form', 'name',
            'Ensure this value has at least 2 characters (it has 1).')
        self.assertFormError(
            response, 'form', 'summary',
            'Ensure this value has at least 2 characters (it has 1).')

        # name and summary individually are okay, but together are too long
        response = self.client.post(
            self.url, self.get_dict(
                name='a' * 50, summary='b' * 50, description='c' * 10))
        assert self.get_addon().name != 'a' * 50
        assert self.get_addon().summary != 'b' * 50
        assert response.status_code == 200
        self.assertFormError(
            response, 'form', 'name',
            'Ensure name and summary combined are at most 70 characters '
            u'(they have 100).')

        # success: together name and summary are 70 characters.
        data = self.get_dict(
            name='a' * 2, summary='b' * 68, description='c' * 10)
        self.is_success(data)

    @override_switch('content-optimization', active=True)
    def test_summary_auto_cropping_content_optimization(self):
        # See test_forms.py::TestDescribeForm for some more variations.
        data = self.get_dict(minimal=False)
        data.pop('name')
        data.pop('summary')
        data.update({
            'name_en-us': 'a' * 25,
            'name_fr': 'b' * 30,
            'summary_en-us': 'c' * 45,
            'summary_fr': 'd' * 45,  # 30 + 45 is > 70
        })
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
        data.update({
            'name_en-us': 'a' * 67,
            'name_fr': 'b' * 69,
            'summary_en-us': 'c' * 2,
            'summary_fr': 'd' * 3,
        })
        self.is_success(data)

        assert self.get_addon().name == 'a' * 67
        assert self.get_addon().summary == 'c' * 2

        with self.activate('fr'):
            assert self.get_addon().name == 'b' * 68
            assert self.get_addon().summary == 'd' * 2


class TestAddonSubmitDetails(DetailsPageMixin, TestSubmitBase):

    def setUp(self):
        super(TestAddonSubmitDetails, self).setUp()
        self.url = reverse('devhub.submit.details', args=['a3615'])

        AddonCategory.objects.filter(
            addon=self.get_addon(),
            category=Category.objects.get(id=1)).delete()
        AddonCategory.objects.filter(
            addon=self.get_addon(),
            category=Category.objects.get(id=71)).delete()

        ctx = self.client.get(self.url).context['cat_form']
        self.cat_initial = initial(ctx.initial_forms[0])
        self.next_step = reverse('devhub.submit.finish', args=['a3615'])
        License.objects.create(builtin=3, on_form=True)
        self.get_addon().update(status=amo.STATUS_NULL)

    def get_dict(self, minimal=True, **kw):
        result = {}
        describe_form = {'name': 'Test name', 'slug': 'testname',
                         'summary': 'Hello!', 'is_experimental': True,
                         'requires_payment': True}
        if not minimal:
            describe_form.update({'description': 'its a description',
                                  'support_url': 'http://stackoverflow.com',
                                  'support_email': 'black@hole.org'})
        cat_initial = kw.pop('cat_initial', self.cat_initial)
        cat_form = formset(cat_initial, initial_count=1)
        license_form = {'license-builtin': 3}
        policy_form = {} if minimal else {
            'has_priv': True, 'privacy_policy': 'Ur data belongs to us now.'}
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
        data = self.get_dict(homepage='foo.com',
                             tags='whatevs, whatever')
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
        assert addon.all_categories[0].id == 22

        # Test add-on log activity.
        log_items = ActivityLog.objects.for_addons(addon)
        assert not log_items.filter(action=amo.LOG.EDIT_PROPERTIES.id), (
            "Setting properties on submit needn't be logged.")

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
            description='its a description', homepage='foo.com',
            tags='whatevs, whatever')
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
        assert addon.all_categories[0].id == 22

        # Test add-on log activity.
        log_items = ActivityLog.objects.for_addons(addon)
        assert not log_items.filter(action=amo.LOG.EDIT_PROPERTIES.id), (
            "Setting properties on submit needn't be logged.")

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
            self.url, self.get_dict(cat_initial=self.cat_initial))
        assert response.context['cat_form'].errors[0]['categories'] == (
            ['This field is required.'])

    def test_submit_categories_max(self):
        assert amo.MAX_CATEGORIES == 2
        self.cat_initial['categories'] = [22, 1, 71]
        response = self.client.post(
            self.url, self.get_dict(cat_initial=self.cat_initial))
        assert response.context['cat_form'].errors[0]['categories'] == (
            ['You can have only 2 categories.'])

    def test_submit_categories_add(self):
        assert [cat.id for cat in self.get_addon().all_categories] == [22]
        self.cat_initial['categories'] = [22, 1]

        self.is_success(self.get_dict())

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        assert sorted(addon_cats) == [1, 22]

    def test_submit_categories_addandremove(self):
        AddonCategory(addon=self.addon, category_id=1).save()
        assert sorted(
            [cat.id for cat in self.get_addon().all_categories]) == [1, 22]

        self.cat_initial['categories'] = [22, 71]
        self.client.post(self.url, self.get_dict(cat_initial=self.cat_initial))
        category_ids_new = [c.id for c in self.get_addon().all_categories]
        assert sorted(category_ids_new) == [22, 71]

    def test_submit_categories_remove(self):
        category = Category.objects.get(id=1)
        AddonCategory(addon=self.addon, category=category).save()
        assert sorted(
            [cat.id for cat in self.get_addon().all_categories]) == [1, 22]

        self.cat_initial['categories'] = [22]
        self.client.post(self.url, self.get_dict(cat_initial=self.cat_initial))
        category_ids_new = [cat.id for cat in self.get_addon().all_categories]
        assert category_ids_new == [22]

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
        response = self.client.post(
            self.url, self.get_dict(**{'license-builtin': 4}))
        assert response.status_code == 200
        self.assertFormError(response, 'license_form', 'builtin',
                             'Select a valid choice. 4 is not one of '
                             'the available choices.')

    def test_set_privacy_nomsg(self):
        """
        You should not get punished with a 500 for not writing your policy...
        but perhaps you should feel shame for lying to us.  This test does not
        test for shame.
        """
        self.get_addon().update(eula=None, privacy_policy=None)
        self.is_success(self.get_dict(has_priv=True))

    def test_source_submission_notes_not_shown_by_default(self):
        url = reverse('devhub.submit.source', args=[self.addon.slug])
        response = self.client.post(url, {
            'has_source': 'no'
        }, follow=True)

        assert response.status_code == 200

        doc = pq(response.content)
        assert 'Remember: ' not in doc('.source-submission-note').text()

    def test_source_submission_notes_shown(self):
        url = reverse('devhub.submit.source', args=[self.addon.slug])

        response = self.client.post(url, {
            'has_source': 'yes', 'source': self.generate_source_zip(),
        }, follow=True)

        assert response.status_code == 200

        doc = pq(response.content)
        assert 'Remember: ' in doc('.source-submission-note').text()


class TestStaticThemeSubmitDetails(DetailsPageMixin, TestSubmitBase):

    def setUp(self):
        super(TestStaticThemeSubmitDetails, self).setUp()
        self.url = reverse('devhub.submit.details', args=['a3615'])

        AddonCategory.objects.filter(
            addon=self.get_addon(),
            category=Category.objects.get(id=1)).delete()
        AddonCategory.objects.filter(
            addon=self.get_addon(),
            category=Category.objects.get(id=22)).delete()
        AddonCategory.objects.filter(
            addon=self.get_addon(),
            category=Category.objects.get(id=71)).delete()
        Category.from_static_category(CATEGORIES_BY_ID[300]).save()  # abstract
        Category.from_static_category(CATEGORIES_BY_ID[308]).save()  # firefox
        Category.from_static_category(CATEGORIES_BY_ID[400]).save()  # abstract
        Category.from_static_category(CATEGORIES_BY_ID[408]).save()  # firefox

        self.next_step = reverse('devhub.submit.finish', args=['a3615'])
        License.objects.create(builtin=11, on_form=True, creative_commons=True)
        self.get_addon().update(
            status=amo.STATUS_NULL, type=amo.ADDON_STATICTHEME)

    def get_dict(self, minimal=True, **kw):
        result = {}
        describe_form = {'name': 'Test name', 'slug': 'testname',
                         'summary': 'Hello!'}
        if not minimal:
            describe_form.update({'support_url': 'http://stackoverflow.com',
                                  'support_email': 'black@hole.org'})
        cat_form = {'category': 'abstract'}
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
        data = self.get_dict(homepage='foo.com',
                             tags='whatevs, whatever')
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
        assert not log_items.filter(action=amo.LOG.EDIT_PROPERTIES.id), (
            "Setting properties on submit needn't be logged.")

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
        self.is_success(self.get_dict(category='firefox'))

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        assert sorted(addon_cats) == [308, 408]

    def test_submit_categories_change(self):
        category_desktop = Category.objects.get(id=300)
        category_android = Category.objects.get(id=400)
        AddonCategory(addon=self.addon, category=category_desktop).save()
        AddonCategory(addon=self.addon, category=category_android).save()
        assert sorted(
            [cat.id for cat in self.get_addon().all_categories]) == [300, 400]

        self.client.post(self.url, self.get_dict(category='firefox'))
        category_ids_new = [cat.id for cat in self.get_addon().all_categories]
        # Only ever one category for Static Themes
        assert category_ids_new == [308, 408]

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
            LICENSES_BY_BUILTIN[11].name)

    def test_set_builtin_license_no_log(self):
        self.is_success(self.get_dict(**{'license-builtin': 11}))
        addon = self.get_addon()
        assert addon.status == amo.STATUS_NOMINATED
        assert addon.current_version.license.builtin == 11
        log_items = ActivityLog.objects.for_addons(self.get_addon())
        assert not log_items.filter(action=amo.LOG.CHANGE_LICENSE.id)

    def test_license_error(self):
        response = self.client.post(
            self.url, self.get_dict(**{'license-builtin': 4}))
        assert response.status_code == 200
        self.assertFormError(response, 'license_form', 'builtin',
                             'Select a valid choice. 4 is not one of '
                             'the available choices.')


class TestAddonSubmitFinish(TestSubmitBase):

    def setUp(self):
        super(TestAddonSubmitFinish, self).setUp()
        self.url = reverse('devhub.submit.finish', args=[self.addon.slug])

    @mock.patch.object(settings, 'EXTERNAL_SITE_URL', 'http://b.ro')
    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay')
    def test_welcome_email_for_newbies(self, send_welcome_email_mock):
        self.client.get(self.url)
        context = {
            'addon_name': 'Delicious Bookmarks',
            'app': str(amo.FIREFOX.pretty),
            'detail_url': 'http://b.ro/en-US/firefox/addon/a3615/',
            'version_url': 'http://b.ro/en-US/developers/addon/a3615/versions',
            'edit_url': 'http://b.ro/en-US/developers/addon/a3615/edit',
        }
        send_welcome_email_mock.assert_called_with(
            self.addon.id, ['del@icio.us'], context)

    @mock.patch.object(settings, 'EXTERNAL_SITE_URL', 'http://b.ro')
    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay')
    def test_welcome_email_first_listed_addon(self, send_welcome_email_mock):
        new_addon = addon_factory(
            version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
        new_addon.addonuser_set.create(user=self.addon.authors.all()[0])
        self.client.get(self.url)
        context = {
            'addon_name': 'Delicious Bookmarks',
            'app': str(amo.FIREFOX.pretty),
            'detail_url': 'http://b.ro/en-US/firefox/addon/a3615/',
            'version_url': 'http://b.ro/en-US/developers/addon/a3615/versions',
            'edit_url': 'http://b.ro/en-US/developers/addon/a3615/edit',
        }
        send_welcome_email_mock.assert_called_with(
            self.addon.id, ['del@icio.us'], context)

    @mock.patch.object(settings, 'EXTERNAL_SITE_URL', 'http://b.ro')
    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay')
    def test_welcome_email_if_previous_addon_is_incomplete(
            self, send_welcome_email_mock):
        # If the developer already submitted an addon but didn't finish or was
        # rejected, we send the email anyway, it might be a dupe depending on
        # how far they got but it's better than not sending any.
        new_addon = addon_factory(status=amo.STATUS_NULL)
        new_addon.addonuser_set.create(user=self.addon.authors.all()[0])
        self.client.get(self.url)
        context = {
            'addon_name': 'Delicious Bookmarks',
            'app': str(amo.FIREFOX.pretty),
            'detail_url': 'http://b.ro/en-US/firefox/addon/a3615/',
            'version_url': 'http://b.ro/en-US/developers/addon/a3615/versions',
            'edit_url': 'http://b.ro/en-US/developers/addon/a3615/edit',
        }
        send_welcome_email_mock.assert_called_with(
            self.addon.id, ['del@icio.us'], context)

    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay')
    def test_no_welcome_email(self, send_welcome_email_mock):
        """You already submitted an add-on? We won't spam again."""
        new_addon = addon_factory(status=amo.STATUS_NOMINATED)
        new_addon.addonuser_set.create(user=self.addon.authors.all()[0])
        self.client.get(self.url)
        assert not send_welcome_email_mock.called

    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay')
    def test_no_welcome_email_if_unlisted(self, send_welcome_email_mock):
        self.make_addon_unlisted(self.addon)
        self.client.get(self.url)
        assert not send_welcome_email_mock.called

    def test_finish_submitting_listed_addon(self):
        version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        assert version.supported_platforms == ([amo.PLATFORM_ALL])

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 3
        # First link is to edit listing
        assert links[0].attrib['href'] == self.addon.get_dev_url()
        # Second link is to edit the version
        assert links[1].attrib['href'] == reverse(
            'devhub.versions.edit',
            args=[self.addon.slug, version.id])
        assert links[1].text == (
            'Edit version %s' % version.version)
        # Third back to my submissions.
        assert links[2].attrib['href'] == reverse('devhub.addons')

    def test_finish_submitting_unlisted_addon(self):
        self.make_addon_unlisted(self.addon)

        self.addon.find_latest_version(channel=amo.RELEASE_CHANNEL_UNLISTED)
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
            response,
            reverse('devhub.submit.version.distribution', args=['a3615']), 302)

    def test_incomplete_directs_to_details(self):
        # We get bounced back to details step.
        self.addon.update(status=amo.STATUS_NULL)
        AddonCategory.objects.filter(addon=self.addon).delete()
        response = self.client.get(
            reverse('devhub.submit.finish', args=['a3615']), follow=True)
        self.assert3xx(
            response, reverse('devhub.submit.details', args=['a3615']))

    def test_finish_submitting_listed_static_theme(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        VersionPreview.objects.create(version=version)
        assert version.supported_platforms == ([amo.PLATFORM_ALL])

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
            response.content)
        # Show the preview we started generating just after the upload step.
        imgs = content('section.addon-submission-process img')
        assert imgs[0].attrib['src'] == (
            version.previews.first().image_url)
        assert len(imgs) == 1  # Just the one preview though.

    def test_finish_submitting_unlisted_static_theme(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        self.make_addon_unlisted(self.addon)

        self.addon.find_latest_version(channel=amo.RELEASE_CHANNEL_UNLISTED)
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
            reverse('devhub.addons.edit', args=['a3615']), follow=True)
        self.assert3xx(
            response, reverse('devhub.submit.details', args=['a3615']))


class TestVersionSubmitDistribution(TestSubmitBase):

    def setUp(self):
        super(TestVersionSubmitDistribution, self).setUp()
        self.url = reverse('devhub.submit.version.distribution',
                           args=[self.addon.slug])

    def test_listed_redirects_to_next_step(self):
        response = self.client.post(self.url, {'channel': 'listed'})
        self.assert3xx(
            response,
            reverse('devhub.submit.version.upload', args=[
                self.addon.slug, 'listed']))

    def test_unlisted_redirects_to_next_step(self):
        response = self.client.post(self.url, {'channel': 'unlisted'})
        self.assert3xx(
            response,
            reverse('devhub.submit.version.upload', args=[
                self.addon.slug, 'unlisted']))

    def test_unlisted_redirects_to_next_step_if_addon_is_invisible(self):
        self.addon.update(disabled_by_user=True)
        response = self.client.post(self.url, {'channel': 'unlisted'})
        self.assert3xx(
            response,
            reverse('devhub.submit.version.upload', args=[
                self.addon.slug, 'unlisted']))

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
        channel_input[0].attrib == {
            'type': 'radio',
            'name': 'channel',
            'value': 'listed',
            'class': 'channel',
            'required': '',
            'id': 'id_channel_0',
            'checked': 'checked'
        }
        channel_input[1].attrib == {
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
        channel_input[0].attrib == {
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
            response,
            reverse('devhub.submit.version.agreement', args=[self.addon.slug]))


class TestVersionSubmitAutoChannel(TestSubmitBase):
    """ Just check we chose the right upload channel.  The upload tests
    themselves are in other tests. """

    def setUp(self):
        super(TestVersionSubmitAutoChannel, self).setUp()
        self.url = reverse('devhub.submit.version', args=[self.addon.slug])

    @mock.patch('olympia.devhub.views._submit_upload',
                side_effect=views._submit_upload)
    def test_listed_last_uses_listed_upload(self, _submit_upload_mock):
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED)
        self.client.post(self.url)
        assert _submit_upload_mock.call_count == 1
        args, _ = _submit_upload_mock.call_args
        assert args[1:] == (
            self.addon, amo.RELEASE_CHANNEL_LISTED,
            'devhub.submit.version.source')

    @mock.patch('olympia.devhub.views._submit_upload',
                side_effect=views._submit_upload)
    def test_unlisted_last_uses_unlisted_upload(self, _submit_upload_mock):
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.client.post(self.url)
        assert _submit_upload_mock.call_count == 1
        args, _ = _submit_upload_mock.call_args
        assert args[1:] == (
            self.addon, amo.RELEASE_CHANNEL_UNLISTED,
            'devhub.submit.version.source')

    def test_no_versions_redirects_to_distribution(self):
        [v.delete() for v in self.addon.versions.all()]
        response = self.client.post(self.url)
        self.assert3xx(
            response,
            reverse('devhub.submit.version.distribution',
                    args=[self.addon.slug]))

    def test_has_read_agreement(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(self.url)
        self.assert3xx(
            response,
            reverse('devhub.submit.version.agreement', args=[self.addon.slug]))


class VersionSubmitUploadMixin(object):
    channel = None
    fixtures = ['base/users', 'base/addon_3615']

    @classmethod
    def setUpTestData(cls):
        create_default_webext_appversion()

    def setUp(self):
        super(VersionSubmitUploadMixin, self).setUp()
        self.upload = self.get_upload('extension.xpi')
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.addon.update(guid='guid@xpi')
        self.user = UserProfile.objects.get(email='del@icio.us')
        assert self.client.login(email=self.user.email)
        self.user.update(last_login_ip='192.168.1.1')
        self.addon.versions.update(channel=self.channel)
        channel = ('listed' if self.channel == amo.RELEASE_CHANNEL_LISTED else
                   'unlisted')
        self.url = reverse('devhub.submit.version.upload',
                           args=[self.addon.slug, channel])
        assert self.addon.has_complete_metadata()
        self.version.save()

    def post(self, compatible_apps=None,
             override_validation=False, expected_status=302, source=None,
             extra_kwargs=None):
        if compatible_apps is None:
            compatible_apps = [amo.FIREFOX]
        data = {
            'upload': self.upload.uuid.hex,
            'compatible_apps': [p.id for p in compatible_apps],
            'admin_override_validation': override_validation
        }
        if source is not None:
            data['source'] = source
        response = self.client.post(self.url, data, **(extra_kwargs or {}))
        assert response.status_code == expected_status
        return response

    def get_next_url(self, version):
        return reverse('devhub.submit.version.source', args=[
            self.addon.slug, version.pk])

    def test_missing_compatibility_apps(self):
        response = self.client.post(self.url, {'upload': self.upload.uuid.hex})
        assert response.status_code == 200
        assert response.context['new_addon_form'].errors.as_text() == (
            '* compatible_apps\n  * Need to select at least one application.')

    def test_unique_version_num(self):
        self.version.update(version='0.1')
        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'Version 0.1 already exists.')

    def test_same_version_if_previous_is_rejected(self):
        # We can't re-use the same version number, even if the previous
        # versions have been disabled/rejected.
        self.version.update(version='0.1')
        self.version.files.update(status=amo.STATUS_DISABLED)
        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'Version 0.1 already exists.')

    def test_same_version_if_previous_is_deleted(self):
        # We can't re-use the same version number if the previous
        # versions has been deleted either.
        self.version.update(version='0.1')
        self.version.delete()
        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'Version 0.1 was uploaded before and deleted.')

    def test_same_version_if_previous_is_awaiting_review(self):
        # We can't re-use the same version number - offer to continue.
        self.version.update(version='0.1')
        self.version.files.update(status=amo.STATUS_AWAITING_REVIEW)
        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'Version 0.1 already exists. '
            'Continue with existing upload instead?')
        # url is always to the details page even for unlisted (will redirect).
        assert pq(response.content)('ul.errorlist a').attr('href') == (
            reverse('devhub.submit.version.details', args=[
                self.addon.slug, self.version.pk]))

    def test_addon_version_is_blocked(self):
        block = Block.objects.create(
            guid=self.addon.guid, updated_by=user_factory())
        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'Version 0.1 matches a blocklist entry for this add-on. '
            'You can contact AMO Admins for additional information.')
        assert pq(response.content)('ul.errorlist a').attr('href') == (
            reverse('blocklist.block', args=[self.addon.guid]))

        # Though we allow if the version is outside of the specified range
        block.update(min_version='0.2')
        response = self.post(expected_status=302), response.content

    def test_distribution_link(self):
        response = self.client.get(self.url)
        channel_text = ('listed' if self.channel == amo.RELEASE_CHANNEL_LISTED
                        else 'unlisted')
        distribution_url = reverse('devhub.submit.version.distribution',
                                   args=[self.addon.slug])
        doc = pq(response.content)
        assert doc('.addon-submit-distribute a').attr('href') == (
            distribution_url + '?channel=' + channel_text)
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
        channel = ('listed' if self.channel == amo.RELEASE_CHANNEL_LISTED else
                   'unlisted')
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#wizardlink')
        assert doc('#wizardlink').attr('href') == (
            reverse('devhub.submit.version.wizard',
                    args=[self.addon.slug, channel]))

    def test_static_theme_wizard(self):
        channel = ('listed' if self.channel == amo.RELEASE_CHANNEL_LISTED else
                   'unlisted')
        self.addon.update(type=amo.ADDON_STATICTHEME)
        # Get the correct template.
        self.url = reverse('devhub.submit.version.wizard',
                           args=[self.addon.slug, channel])
        mock_point = 'olympia.devhub.views.extract_theme_properties'
        with mock.patch(mock_point) as extract_theme_properties_mock:
            extract_theme_properties_mock.return_value = {
                'colors': {
                    'frame': '#123456',
                    'tab_background_text': 'rgba(1,2,3,0.4)',
                },
                'images': {
                    'theme_frame': 'header.png',
                }
            }
            response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#theme-wizard')
        assert doc('#theme-wizard').attr('data-version') == '3.0'
        assert doc('input#theme-name').attr('type') == 'hidden'
        assert doc('input#theme-name').attr('value') == (
            str(self.addon.name))
        # Existing colors should be the default values for the fields
        assert doc('#frame').attr('value') == '#123456'
        assert doc('#tab_background_text').attr('value') == 'rgba(1,2,3,0.4)'
        # And the theme header url is there for the JS to load
        assert doc('#theme-header').attr('data-existing-header') == (
            'header.png')
        # No warning about extra properties
        assert b'are unsupported in this wizard' not in response.content

        # And then check the upload works.
        path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip')
        self.upload = self.get_upload(abspath=path)
        response = self.post()

        version = self.addon.find_latest_version(channel=self.channel)
        assert version.channel == self.channel
        assert version.all_files[0].status == amo.STATUS_AWAITING_REVIEW
        self.assert3xx(response, self.get_next_url(version))
        log_items = ActivityLog.objects.for_addons(self.addon)
        assert log_items.filter(action=amo.LOG.ADD_VERSION.id)
        if self.channel == amo.RELEASE_CHANNEL_LISTED:
            previews = list(version.previews.all())
            assert len(previews) == 3
            assert storage.exists(previews[0].image_path)
            assert storage.exists(previews[1].image_path)
            assert storage.exists(previews[1].image_path)
        else:
            assert version.previews.all().count() == 0

    def test_static_theme_wizard_unsupported_properties(self):
        channel = ('listed' if self.channel == amo.RELEASE_CHANNEL_LISTED else
                   'unlisted')
        self.addon.update(type=amo.ADDON_STATICTHEME)
        # Get the correct template.
        self.url = reverse('devhub.submit.version.wizard',
                           args=[self.addon.slug, channel])
        mock_point = 'olympia.devhub.views.extract_theme_properties'
        with mock.patch(mock_point) as extract_theme_properties_mock:
            extract_theme_properties_mock.return_value = {
                'colors': {
                    'frame': '#123456',
                    'tab_background_text': 'rgba(1,2,3,0.4)',
                    'tab_line': '#123',
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
        assert doc('input#theme-name').attr('value') == (
            str(self.addon.name))
        # Existing colors should be the default values for the fields
        assert doc('#frame').attr('value') == '#123456'
        assert doc('#tab_background_text').attr('value') == 'rgba(1,2,3,0.4)'
        # Warning about extra properties this time:
        assert b'are unsupported in this wizard' in response.content
        unsupported_list = doc('.notification-box.error ul.note li')
        assert unsupported_list.length == 3
        assert 'tab_line' in unsupported_list.text()
        assert 'additional_backgrounds' in unsupported_list.text()
        assert 'something_extra' in unsupported_list.text()

        # And then check the upload works.
        path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip')
        self.upload = self.get_upload(abspath=path)
        response = self.post()

        version = self.addon.find_latest_version(channel=self.channel)
        assert version.channel == self.channel
        assert version.all_files[0].status == amo.STATUS_AWAITING_REVIEW
        self.assert3xx(response, self.get_next_url(version))
        log_items = ActivityLog.objects.for_addons(self.addon)
        assert log_items.filter(action=amo.LOG.ADD_VERSION.id)
        if self.channel == amo.RELEASE_CHANNEL_LISTED:
            previews = list(version.previews.all())
            assert len(previews) == 3
            assert storage.exists(previews[0].image_path)
            assert storage.exists(previews[1].image_path)
            assert storage.exists(previews[1].image_path)
        else:
            assert version.previews.all().count() == 0

    @mock.patch('olympia.devhub.forms.parse_addon',
                wraps=_parse_addon_theme_permission_wrapper)
    def test_dynamic_theme_tagging(self, parse_addon_mock):
        self.addon.update(guid='beastify@mozilla.org')
        path = os.path.join(
            settings.ROOT,
            'src/olympia/devhub/tests/addons/valid_webextension.xpi')
        self.upload = self.get_upload(abspath=path)
        response = self.post()
        version = self.addon.find_latest_version(channel=self.channel)
        self.assert3xx(
            response, self.get_next_url(version))
        if self.channel == amo.RELEASE_CHANNEL_LISTED:
            assert self.addon.tags.filter(tag_text='dynamic theme').exists()
        else:
            assert not self.addon.tags.filter(
                tag_text='dynamic theme').exists()


class TestVersionSubmitUploadListed(VersionSubmitUploadMixin, UploadTest):
    channel = amo.RELEASE_CHANNEL_LISTED

    def test_success(self):
        response = self.post()
        version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        assert version.channel == amo.RELEASE_CHANNEL_LISTED
        assert version.all_files[0].status == amo.STATUS_AWAITING_REVIEW
        self.assert3xx(response, self.get_next_url(version))
        log_items = ActivityLog.objects.for_addons(self.addon)
        assert log_items.filter(action=amo.LOG.ADD_VERSION.id)

    def test_experiment_inside_webext_upload_without_permission(self):
        self.upload = self.get_upload(
            'experiment_inside_webextension.xpi',
            validation=json.dumps({
                "notices": 2, "errors": 0, "messages": [],
                "metadata": {}, "warnings": 1,
            }))
        self.addon.update(
            guid='@experiment-inside-webextension-guid',
            status=amo.STATUS_APPROVED)

        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'You cannot submit this type of add-on')

    def test_theme_experiment_inside_webext_upload_without_permission(self):
        self.upload = self.get_upload(
            'theme_experiment_inside_webextension.xpi',
            validation=json.dumps({
                "notices": 2, "errors": 0, "messages": [],
                "metadata": {}, "warnings": 1,
            }))
        self.addon.update(
            guid='@theme–experiment-inside-webextension-guid',
            status=amo.STATUS_APPROVED)

        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'You cannot submit this type of add-on')

    def test_incomplete_addon_now_nominated(self):
        """Uploading a new version for an incomplete addon should set it to
        nominated."""
        self.addon.current_version.files.update(status=amo.STATUS_DISABLED)
        self.addon.update_status()
        # Deleting all the versions should make it null.
        assert self.addon.status == amo.STATUS_NULL
        self.post()
        self.addon.reload()
        assert self.addon.status == amo.STATUS_NOMINATED

    def test_langpack_requires_permission(self):
        self.upload = self.get_upload(
            'webextension_langpack.xpi',
            validation=json.dumps({
                "notices": 2, "errors": 0, "messages": [],
                "metadata": {}, "warnings": 1,
            }))

        self.addon.update(type=amo.ADDON_LPAPP)

        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'You cannot submit a language pack')

        self.grant_permission(
            self.user, ':'.join(amo.permissions.LANGPACK_SUBMIT))

        response = self.post(expected_status=302)

        version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)

        self.assert3xx(
            response,
            reverse(
                'devhub.submit.version.source',
                args=[self.addon.slug, version.pk]))

    def test_redirect_if_addon_is_invisible(self):
        self.addon.update(disabled_by_user=True)
        # We should be redirected to the "distribution" page, because we tried
        # to access the listed upload page while the add-on was "invisible".
        response = self.client.get(self.url)
        self.assert3xx(
            response, reverse('devhub.submit.version.distribution',
                              args=[self.addon.slug]), 302)

        # Same for posts.
        response = self.post(expected_status=302)
        self.assert3xx(
            response, reverse('devhub.submit.version.distribution',
                              args=[self.addon.slug]), 302)


class TestVersionSubmitUploadUnlisted(VersionSubmitUploadMixin, UploadTest):
    channel = amo.RELEASE_CHANNEL_UNLISTED

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
            'extension.xpi', validation=json.dumps(result))
        response = self.post()
        version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert version.channel == amo.RELEASE_CHANNEL_UNLISTED
        assert version.all_files[0].status == amo.STATUS_AWAITING_REVIEW
        self.assert3xx(response, self.get_next_url(version))

    def test_show_warning_and_remove_change_link_if_addon_is_invisible(self):
        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        # Channel should be 'unlisted' with a warning shown, no choice about it
        # since the add-on is "invisible".
        assert doc('p.status-disabled')
        # The link to select another distribution channel should be absent.
        assert not doc('.addon-submit-distribute a')


class TestVersionSubmitSource(TestAddonSubmitSource):

    def setUp(self):
        super(TestVersionSubmitSource, self).setUp()
        addon = self.get_addon()
        self.version = version_factory(
            addon=addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            license_id=addon.versions.latest().license_id)
        self.url = reverse(
            'devhub.submit.version.source', args=[addon.slug, self.version.pk])
        self.next_url = reverse(
            'devhub.submit.version.details',
            args=[addon.slug, self.version.pk])
        assert not self.get_version().source


class TestVersionSubmitDetails(TestSubmitBase):

    def setUp(self):
        super(TestVersionSubmitDetails, self).setUp()
        addon = self.get_addon()
        self.version = version_factory(
            addon=addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            license_id=addon.versions.latest().license_id)
        self.url = reverse('devhub.submit.version.details',
                           args=[addon.slug, self.version.pk])

    def test_submit_empty_is_okay(self):
        assert all(self.get_addon().get_required_metadata())
        response = self.client.get(self.url)
        assert response.status_code == 200

        response = self.client.post(self.url, {})
        self.assert3xx(
            response, reverse('devhub.submit.version.finish',
                              args=[self.addon.slug, self.version.pk]))

        assert not self.version.approval_notes
        assert not self.version.release_notes

    def test_submit_success(self):
        assert all(self.get_addon().get_required_metadata())
        response = self.client.get(self.url)
        assert response.status_code == 200

        # Post and be redirected - trying to sneak in a field that shouldn't
        # be modified when this is not the first listed version.
        data = {'approval_notes': 'approove plz',
                'release_notes': 'loadsa stuff', 'name': 'foo'}
        response = self.client.post(self.url, data)
        self.assert3xx(
            response, reverse('devhub.submit.version.finish',
                              args=[self.addon.slug, self.version.pk]))

        # This field should not have been modified.
        assert self.get_addon().name != 'foo'

        self.version.reload()
        assert self.version.approval_notes == 'approove plz'
        assert self.version.release_notes == 'loadsa stuff'

    def test_submit_details_unlisted_should_redirect(self):
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert all(self.get_addon().get_required_metadata())
        response = self.client.get(self.url)
        self.assert3xx(
            response, reverse('devhub.submit.version.finish',
                              args=[self.addon.slug, self.version.pk]))

    def test_show_request_for_information(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon, pending_info_request=self.days_ago(2))
        ActivityLog.create(
            amo.LOG.REVIEWER_REPLY_VERSION, self.addon, self.version,
            user=self.user, details={'comments': 'this should not be shown'})
        ActivityLog.create(
            amo.LOG.REQUEST_INFORMATION, self.addon, self.version,
            user=self.user, details={'comments': 'this is an info request'})
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b'this should not be shown' not in response.content
        assert b'this is an info request' in response.content

    def test_dont_show_request_for_information_if_none_pending(self):
        ActivityLog.create(
            amo.LOG.REVIEWER_REPLY_VERSION, self.addon, self.version,
            user=self.user, details={'comments': 'this should not be shown'})
        ActivityLog.create(
            amo.LOG.REQUEST_INFORMATION, self.addon, self.version,
            user=self.user, details={'comments': 'this is an info request'})
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b'this should not be shown' not in response.content
        assert b'this is an info request' not in response.content

    def test_clear_request_for_information(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon, pending_info_request=self.days_ago(2))
        response = self.client.post(
            self.url, {'clear_pending_info_request': True})
        self.assert3xx(
            response, reverse('devhub.submit.version.finish',
                              args=[self.addon.slug, self.version.pk]))
        flags = AddonReviewerFlags.objects.get(addon=self.addon)
        assert flags.pending_info_request is None
        activity = ActivityLog.objects.for_addons(self.addon).filter(
            action=amo.LOG.DEVELOPER_CLEAR_INFO_REQUEST.id).get()
        assert activity.user == self.user
        assert activity.arguments == [self.addon, self.version]

    def test_dont_clear_request_for_information(self):
        past_date = self.days_ago(2)
        AddonReviewerFlags.objects.create(
            addon=self.addon, pending_info_request=past_date)
        response = self.client.post(self.url)
        self.assert3xx(
            response, reverse('devhub.submit.version.finish',
                              args=[self.addon.slug, self.version.pk]))
        flags = AddonReviewerFlags.objects.get(addon=self.addon)
        assert flags.pending_info_request == past_date
        assert not ActivityLog.objects.for_addons(self.addon).filter(
            action=amo.LOG.DEVELOPER_CLEAR_INFO_REQUEST.id).exists()

    def test_can_cancel_review(self):
        addon = self.get_addon()
        addon_status = addon.status
        addon.versions.latest().files.update(status=amo.STATUS_AWAITING_REVIEW)

        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        versions_url = reverse('devhub.addons.versions', args=['a3615'])
        response = self.client.post(cancel_url)
        self.assert3xx(response, versions_url)

        addon = self.get_addon()
        assert addon.status == addon_status  # No change.
        version = addon.versions.latest()
        del version.all_files
        assert version.statuses == [
            (version.all_files[0].id, amo.STATUS_DISABLED)]

    def test_public_addon_stays_public_even_if_had_missing_metadata(self):
        """Posting details for a new version for a public add-on that somehow
        had missing metadata despite being public shouldn't reset it to
        nominated."""
        # Create a built-in License we'll use later when posting.
        License.objects.create(builtin=3, on_form=True)

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

            'form-0-categories': [22, 1],
            'form-0-application': 1,
            'form-INITIAL_FORMS': 1,
            'form-TOTAL_FORMS': 1,

            'license-builtin': 3,
        }
        response = self.client.post(self.url, data)
        self.assert3xx(
            response, reverse('devhub.submit.version.finish',
                              args=[self.addon.slug, self.version.pk]))
        self.addon.reload()
        assert self.addon.has_complete_metadata()
        assert self.addon.status == amo.STATUS_APPROVED

    def test_submit_static_theme_should_redirect(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        assert all(self.get_addon().get_required_metadata())
        response = self.client.get(self.url)
        # No extra details for subsequent theme uploads so just redirect.
        self.assert3xx(
            response, reverse('devhub.submit.version.finish',
                              args=[self.addon.slug, self.version.pk]))


class TestVersionSubmitDetailsFirstListed(TestAddonSubmitDetails):
    """ Testing the case of a listed version being submitted on an add-on that
    previously only had unlisted versions - so is missing metadata."""
    def setUp(self):
        super(TestVersionSubmitDetailsFirstListed, self).setUp()
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.version = version_factory(addon=self.addon,
                                       channel=amo.RELEASE_CHANNEL_LISTED)
        self.version.update(license=None)  # Addon needs to be missing data.
        self.url = reverse('devhub.submit.version.details',
                           args=['a3615', self.version.pk])
        self.next_step = reverse('devhub.submit.version.finish',
                                 args=['a3615', self.version.pk])


class TestVersionSubmitFinish(TestAddonSubmitFinish):

    def setUp(self):
        super(TestVersionSubmitFinish, self).setUp()
        addon = self.get_addon()
        self.version = version_factory(
            addon=addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            license_id=addon.versions.latest().license_id,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        self.url = reverse('devhub.submit.version.finish',
                           args=[addon.slug, self.version.pk])

    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay')
    def test_no_welcome_email(self, send_welcome_email_mock):
        """No emails for version finish."""
        self.client.get(self.url)
        assert not send_welcome_email_mock.called

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
