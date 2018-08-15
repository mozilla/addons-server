import json
import os
import stat

from datetime import datetime, timedelta

from django.conf import settings
from django.core.files import temp
from django.core.files.storage import default_storage as storage
from django.test.utils import override_settings

import mock

from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import (
    Addon, AddonCategory, AddonReviewerFlags, Category)
from olympia.amo.tests import (
    TestCase, addon_factory, formset, initial, version_factory)
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import reverse
from olympia.constants.categories import CATEGORIES_BY_ID
from olympia.constants.licenses import LICENSES_BY_BUILTIN
from olympia.devhub import views
from olympia.files.models import FileValidation
from olympia.files.tests.test_models import UploadTest
from olympia.files.utils import parse_addon
from olympia.users.models import UserProfile
from olympia.versions.models import License, VersionPreview
from olympia.zadmin.models import Config, set_config


def get_addon_count(name):
    """Return the number of addons with the given name."""
    return Addon.unfiltered.filter(name__localized_string=name).count()


def _parse_addon_theme_permission_wrapper(*args, **kwargs):
    parsed = parse_addon(*args, **kwargs)
    parsed['permissions'] = parsed.get('permissions', []) + ['theme']
    return parsed


class TestSubmitPersona(TestCase):
    fixtures = ['base/user_999']

    def setUp(self):
        super(TestSubmitPersona, self).setUp()
        assert self.client.login(email='regular@mozilla.com')
        self.url = reverse('devhub.themes.submit')

    def get_img_urls(self):
        return (
            reverse('devhub.personas.upload_persona', args=['persona_header']),
        )

    def test_img_urls(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        header_url = self.get_img_urls()[0]
        assert doc('#id_header').attr('data-upload-url') == header_url

    def test_img_size(self):
        img = get_image_path('mozilla.png')
        for url, img_type in zip(self.get_img_urls(), ('header', )):
            r_ajax = self.client.post(url, {'upload_image': open(img, 'rb')})
            r_json = json.loads(r_ajax.content)
            w, h = amo.PERSONA_IMAGE_SIZES.get(img_type)[1]
            assert r_json['errors'] == [
                'Image must be exactly %s pixels wide '
                'and %s pixels tall.' % (w, h)]

    def test_img_wrongtype(self):
        img = open('static/js/impala/global.js', 'rb')
        for url in self.get_img_urls():
            r_ajax = self.client.post(url, {'upload_image': img})
            r_json = json.loads(r_ajax.content)
            assert r_json['errors'] == ['Images must be either PNG or JPG.']


class TestSubmitBase(TestCase):
    fixtures = ['base/addon_3615', 'base/addon_5579', 'base/users']

    def setUp(self):
        super(TestSubmitBase, self).setUp()
        assert self.client.login(email='del@icio.us')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.addon = self.get_addon()

    def get_addon(self):
        return Addon.objects.get(pk=3615)

    def get_version(self):
        return self.get_addon().versions.latest()


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
        set_config('last_dev_agreement_change_date', '2018-01-01 00:00')
        before_agreement_last_changed = (
            datetime(2018, 1, 1) - timedelta(days=1))
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
        after_agreement_last_changed = (
            datetime(2018, 1, 1) + timedelta(days=1))
        self.user.update(read_dev_agreement=after_agreement_last_changed)
        response = self.client.get(reverse('devhub.submit.agreement'))
        self.assert3xx(response, reverse('devhub.submit.distribution'))

    def test_read_dev_agreement_set_to_future(self):
        set_config('last_dev_agreement_change_date', '2099-12-31 00:00')
        read_dev_date = datetime(2018, 1, 1)
        self.user.update(read_dev_agreement=read_dev_date)
        response = self.client.get(reverse('devhub.submit.agreement'))
        self.assert3xx(response, reverse('devhub.submit.distribution'))

    def test_read_dev_agreement_set_to_future_not_agreed_yet(self):
        set_config('last_dev_agreement_change_date', '2099-12-31 00:00')
        self.user.update(read_dev_agreement=None)
        response = self.client.get(reverse('devhub.submit.agreement'))
        assert response.status_code == 200
        assert 'agreement_form' in response.context

    def test_read_dev_agreement_invalid_date_agreed_post_fallback(self):
        set_config('last_dev_agreement_change_date', '2099-25-75 00:00')
        read_dev_date = datetime(2018, 1, 1)
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


class TestAddonSubmitDistribution(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestAddonSubmitDistribution, self).setUp()
        self.client.login(email='regular@mozilla.com')
        self.user = UserProfile.objects.get(email='regular@mozilla.com')

    def test_check_agreement_okay(self):
        response = self.client.post(reverse('devhub.submit.agreement'))
        self.assert3xx(response, reverse('devhub.submit.distribution'))
        response = self.client.get(reverse('devhub.submit.distribution'))
        assert response.status_code == 200
        # No error shown for a redirect from previous step.
        assert 'This field is required' not in response.content

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
        set_config('last_dev_agreement_change_date', '2018-01-01 00:00')
        before_agreement_last_changed = (
            datetime(2018, 1, 1) - timedelta(days=1))
        self.user.update(read_dev_agreement=before_agreement_last_changed)
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
        assert 'This field is required' not in self.client.get(url).content

        # Load with channel preselected (e.g. back from next step) - no error.
        assert 'This field is required' not in self.client.get(
            url, args=['listed']).content

        # A post submission without channel selection should be an error
        assert 'This field is required' in self.client.post(url).content


class TestAddonSubmitUpload(UploadTest, TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestAddonSubmitUpload, self).setUp()
        self.upload = self.get_upload('extension.xpi')
        assert self.client.login(email='regular@mozilla.com')
        self.client.post(reverse('devhub.submit.agreement'))

    def post(self, supported_platforms=None, expect_errors=False,
             listed=True, status_code=200, url=None):
        if supported_platforms is None:
            supported_platforms = [amo.PLATFORM_ALL]
        data = {
            'upload': self.upload.uuid.hex,
            'supported_platforms': [p.id for p in supported_platforms]
        }
        url = url or reverse('devhub.submit.upload',
                             args=['listed' if listed else 'unlisted'])
        response = self.client.post(url, data, follow=True)
        assert response.status_code == status_code
        if not expect_errors:
            # Show any unexpected form errors.
            if response.context and 'new_addon_form' in response.context:
                assert (
                    response.context['new_addon_form'].errors.as_text() == '')
        return response

    def test_unique_name(self):
        addon_factory(name='xpi name')
        self.post(expect_errors=False)

    def test_unlisted_name_not_unique(self):
        """We don't enforce name uniqueness for unlisted add-ons."""
        addon_factory(name='xpi name',
                      version_kw={'channel': amo.RELEASE_CHANNEL_LISTED})
        assert get_addon_count('xpi name') == 1
        # We're not passing `expected_errors=True`, so if there was any errors
        # like "This name is already in use. Please choose another one", the
        # test would fail.
        response = self.post()
        # Kind of redundant with the `self.post()` above: we just want to make
        # really sure there's no errors raised by posting an add-on with a name
        # that is already used by an unlisted add-on.
        assert 'new_addon_form' not in response.context
        assert get_addon_count('xpi name') == 2

    def test_name_not_unique_between_types(self):
        """We don't enforce name uniqueness between add-ons types."""
        addon_factory(name='xpi name', type=amo.ADDON_THEME)
        assert get_addon_count('xpi name') == 1
        # We're not passing `expected_errors=True`, so if there was any errors
        # like "This name is already in use. Please choose another one", the
        # test would fail.
        response = self.post()
        # Kind of redundant with the `self.post()` above: we just want to make
        # really sure there's no errors raised by posting an add-on with a name
        # that is already used by an unlisted add-on.
        assert 'new_addon_form' not in response.context
        assert get_addon_count('xpi name') == 2

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

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_success_unlisted(self, mock_sign_file):
        """Sign automatically."""
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
        assert version.channel == amo.RELEASE_CHANNEL_UNLISTED
        assert addon.status == amo.STATUS_NULL
        assert mock_sign_file.called
        assert not addon.tags.filter(tag_text='dynamic theme').exists()

    def test_missing_platforms(self):
        url = reverse('devhub.submit.upload', args=['listed'])
        response = self.client.post(url, {'upload': self.upload.uuid.hex})
        assert response.status_code == 200
        assert response.context['new_addon_form'].errors.as_text() == (
            '* supported_platforms\n  * Need at least one platform.')
        doc = pq(response.content)
        assert doc('ul.errorlist').text() == (
            'Need at least one platform.')

    def test_one_xpi_for_multiple_platforms(self):
        assert Addon.objects.count() == 0
        response = self.post(
            supported_platforms=[amo.PLATFORM_MAC, amo.PLATFORM_LINUX])
        addon = Addon.objects.get()
        self.assert3xx(
            response, reverse('devhub.submit.source', args=[addon.slug]))
        all_ = sorted([f.filename for f in addon.current_version.all_files])
        assert all_ == [u'xpi_name-0.1-linux.xpi', u'xpi_name-0.1-mac.xpi']

    @mock.patch('olympia.devhub.views.auto_sign_file')
    def test_one_xpi_for_multiple_platforms_unlisted_addon(
            self, mock_auto_sign_file):
        assert Addon.objects.count() == 0
        response = self.post(
            supported_platforms=[amo.PLATFORM_MAC, amo.PLATFORM_LINUX],
            listed=False)
        addon = Addon.unfiltered.get()
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.assert3xx(
            response, reverse('devhub.submit.source', args=[addon.slug]))
        all_ = sorted([f.filename for f in latest_version.all_files])
        assert all_ == [u'xpi_name-0.1-linux.xpi', u'xpi_name-0.1-mac.xpi']
        mock_auto_sign_file.assert_has_calls([
            mock.call(f)
            for f in latest_version.all_files])

    @override_switch('allow-static-theme-uploads', active=True)
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

    @override_switch('allow-static-theme-uploads', active=False)
    def test_static_theme_wizard_button_not_shown(self):
        response = self.client.get(reverse(
            'devhub.submit.upload', args=['listed']), follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#wizardlink')

        response = self.client.get(reverse(
            'devhub.submit.upload', args=['unlisted']), follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#wizardlink')

    @override_switch('allow-static-theme-uploads', active=True)
    def test_static_theme_submit_listed(self):
        assert Addon.objects.count() == 0
        path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip')
        self.upload = self.get_upload(abspath=path)
        response = self.post(
            # Throw in platforms for the lols - they will be ignored
            supported_platforms=[amo.PLATFORM_MAC, amo.PLATFORM_LINUX])
        addon = Addon.objects.get()
        self.assert3xx(
            response, reverse('devhub.submit.details', args=[addon.slug]))
        all_ = sorted([f.filename for f in addon.current_version.all_files])
        assert all_ == [u'weta_fade-1.0.xpi']  # One XPI for all platforms.
        assert addon.type == amo.ADDON_STATICTHEME
        previews = list(addon.current_version.previews.all())
        assert len(previews) == 2
        assert storage.exists(previews[0].image_path)
        assert storage.exists(previews[1].image_path)

    @override_switch('allow-static-theme-uploads', active=True)
    def test_static_theme_submit_unlisted(self):
        assert Addon.unfiltered.count() == 0
        path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip')
        self.upload = self.get_upload(abspath=path)
        response = self.post(
            # Throw in platforms for the lols - they will be ignored
            supported_platforms=[amo.PLATFORM_MAC, amo.PLATFORM_LINUX],
            listed=False)
        addon = Addon.unfiltered.get()
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.assert3xx(
            response, reverse('devhub.submit.finish', args=[addon.slug]))
        all_ = sorted([f.filename for f in latest_version.all_files])
        assert all_ == [u'weta_fade-1.0.xpi']  # One XPI for all platforms.
        assert addon.type == amo.ADDON_STATICTHEME
        # Only listed submissions need a preview generated.
        assert latest_version.previews.all().count() == 0

    @override_switch('allow-static-theme-uploads', active=True)
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
        response = self.post(
            url=url,
            # Throw in platforms for the lols - they will be ignored
            supported_platforms=[amo.PLATFORM_MAC, amo.PLATFORM_LINUX])
        addon = Addon.objects.get()
        # Next step is same as non-wizard flow too.
        self.assert3xx(
            response, reverse('devhub.submit.details', args=[addon.slug]))
        all_ = sorted([f.filename for f in addon.current_version.all_files])
        assert all_ == [u'weta_fade-1.0.xpi']  # One XPI for all platforms.
        assert addon.type == amo.ADDON_STATICTHEME
        previews = list(addon.current_version.previews.all())
        assert len(previews) == 2
        assert storage.exists(previews[0].image_path)
        assert storage.exists(previews[1].image_path)

    @override_switch('allow-static-theme-uploads', active=True)
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
        response = self.post(
            url=url,
            # Throw in platforms for the lols - they will be ignored
            supported_platforms=[amo.PLATFORM_MAC, amo.PLATFORM_LINUX],
            listed=False)
        addon = Addon.unfiltered.get()
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        # Next step is same as non-wizard flow too.
        self.assert3xx(
            response, reverse('devhub.submit.finish', args=[addon.slug]))
        all_ = sorted([f.filename for f in latest_version.all_files])
        assert all_ == [u'weta_fade-1.0.xpi']  # One XPI for all platforms.
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
            'source': source,
        }
        response = self.client.post(self.url, data, follow=True)
        assert response.status_code == status_code
        if not expect_errors:
            # Show any unexpected form errors.
            if response.context and 'form' in response.context:
                assert response.context['form'].errors == {}
        return response

    def get_source(self, suffix='.zip'):
        tdir = temp.gettempdir()
        source = temp.NamedTemporaryFile(suffix=suffix, dir=tdir)
        source.write('a' * (2 ** 21))
        source.seek(0)
        return source

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=1)
    def test_submit_source(self):
        response = self.post(has_source=True, source=self.get_source())
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert self.get_version().source
        assert self.addon.needs_admin_code_review
        mode = (
            oct(os.stat(self.get_version().source.path)[stat.ST_MODE]))
        assert mode == '0100644'

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=1)
    def test_say_no_but_submit_source_anyway_fails(self):
        response = self.post(
            has_source=False, source=self.get_source(), expect_errors=True)
        assert response.context['form'].errors == {
            'has_source': [
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
            'has_source': [u'You have not uploaded a source file.']
        }
        self.addon = self.addon.reload()
        assert not self.get_version().source
        assert not self.addon.needs_admin_code_review

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=2 ** 22)
    def test_submit_source_in_memory_upload(self):
        response = self.post(has_source=True, source=self.get_source())
        self.assert3xx(response, self.next_url)
        self.addon = self.addon.reload()
        assert self.get_version().source
        assert self.addon.needs_admin_code_review
        mode = (
            oct(os.stat(self.get_version().source.path)[stat.ST_MODE]))
        assert mode == '0100644'

    def test_with_bad_source_format(self):
        response = self.post(
            has_source=True, source=self.get_source(suffix='.exe'),
            expect_errors=True)
        assert response.context['form'].errors == {
            'source': [
                u"Unsupported file type, please upload an archive file "
                "('.zip', '.tar', '.7z', '.tar.gz', '.tgz', '.tbz', '.txz', "
                "'.tar.bz2', '.tar.xz')."],
            # Django deletes the source data from the cleaned form data
            # in case of an error on a field, so that `source` doesn't
            # exist for the `has_source` check
            'has_source': [u'You have not uploaded a source file.']
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
            describe_form.update({'support_url': 'http://stackoverflow.com',
                                  'support_email': 'black@hole.org'})
        cat_initial = kw.pop('cat_initial', self.cat_initial)
        cat_form = formset(cat_initial, initial_count=1)
        license_form = {'license-builtin': 3}
        policy_form = {} if minimal else {
            'has_priv': True, 'privacy_policy': 'Ur data belongs to us now.'}
        reviewer_form = {} if minimal else {'approvalnotes': 'approove plz'}
        result.update(describe_form)
        result.update(cat_form)
        result.update(license_form)
        result.update(policy_form)
        result.update(reviewer_form)
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
        assert addon.is_experimental
        assert addon.requires_payment
        assert addon.all_categories[0].id == 22

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
        assert addon.privacy_policy == 'Ur data belongs to us now.'
        assert addon.current_version.approvalnotes == 'approove plz'

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
        Category.from_static_category(CATEGORIES_BY_ID[300]).save()
        Category.from_static_category(CATEGORIES_BY_ID[308]).save()

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
        cat_form = {'category': 300}
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
        self.is_success(self.get_dict(category=308))

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        assert sorted(addon_cats) == [308]

    def test_submit_categories_change(self):
        category = Category.objects.get(id=300)
        AddonCategory(addon=self.addon, category=category).save()
        assert sorted(
            [cat.id for cat in self.get_addon().all_categories]) == [300]

        self.client.post(self.url, self.get_dict(category=308))
        category_ids_new = [cat.id for cat in self.get_addon().all_categories]
        # Only ever one category for Static Themes
        assert category_ids_new == [308]

    def test_creative_commons_licenses(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        content = doc('.addon-submission-process')
        assert content('#cc-chooser')  # cc license wizard
        assert content('#persona-license')  # cc license result
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

    @mock.patch.object(settings, 'SITE_URL', 'http://b.ro')
    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay')
    def test_welcome_email_for_newbies(self, send_welcome_email_mock):
        self.client.get(self.url)
        context = {
            'addon_name': 'Delicious Bookmarks',
            'app': unicode(amo.FIREFOX.pretty),
            'detail_url': 'http://b.ro/en-US/firefox/addon/a3615/',
            'version_url': 'http://b.ro/en-US/developers/addon/a3615/versions',
            'edit_url': 'http://b.ro/en-US/developers/addon/a3615/edit',
        }
        send_welcome_email_mock.assert_called_with(
            self.addon.id, ['del@icio.us'], context)

    @mock.patch.object(settings, 'SITE_URL', 'http://b.ro')
    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay')
    def test_welcome_email_first_listed_addon(self, send_welcome_email_mock):
        new_addon = addon_factory(
            version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
        new_addon.addonuser_set.create(user=self.addon.authors.all()[0])
        self.client.get(self.url)
        context = {
            'addon_name': 'Delicious Bookmarks',
            'app': unicode(amo.FIREFOX.pretty),
            'detail_url': 'http://b.ro/en-US/firefox/addon/a3615/',
            'version_url': 'http://b.ro/en-US/developers/addon/a3615/versions',
            'edit_url': 'http://b.ro/en-US/developers/addon/a3615/edit',
        }
        send_welcome_email_mock.assert_called_with(
            self.addon.id, ['del@icio.us'], context)

    @mock.patch.object(settings, 'SITE_URL', 'http://b.ro')
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
            'app': unicode(amo.FIREFOX.pretty),
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

        latest_version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 2
        # First link is to the file download.
        file_ = latest_version.all_files[-1]
        assert links[0].attrib['href'] == file_.get_url_path('devhub')
        assert links[0].text == (
            'Download %s' % file_.filename)
        # Second back to my submissions.
        assert links[1].attrib['href'] == reverse('devhub.addons')

    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay', new=mock.Mock)
    def test_finish_submitting_platform_specific_listed_addon(self):
        latest_version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        latest_version.all_files[0].update(
            status=amo.STATUS_AWAITING_REVIEW, platform=amo.PLATFORM_MAC.id)
        latest_version.save()
        assert latest_version.is_allowed_upload()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 4
        # First link is to edit listing
        assert links[0].attrib['href'] == self.addon.get_dev_url()
        # Second link is to edit the version
        assert links[1].attrib['href'] == reverse(
            'devhub.versions.edit',
            args=[self.addon.slug, latest_version.id])
        assert links[1].text == (
            'Edit version %s' % latest_version.version)
        # Third link is to add a new file.
        assert links[2].attrib['href'] == reverse(
            'devhub.submit.file', args=[self.addon.slug, latest_version.id])
        # Fourth back to my submissions.
        assert links[3].attrib['href'] == reverse('devhub.addons')

    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay', new=mock.Mock)
    def test_finish_submitting_platform_specific_unlisted_addon(self):
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        latest_version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        latest_version.all_files[0].update(
            status=amo.STATUS_AWAITING_REVIEW, platform=amo.PLATFORM_MAC.id)
        latest_version.save()
        assert latest_version.is_allowed_upload()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 3
        # First link is to the file download.
        file_ = latest_version.all_files[-1]
        assert links[0].attrib['href'] == file_.get_url_path('devhub')
        assert links[0].text == (
            'Download %s' % file_.filename)
        # Second link is to add a new file.
        assert links[1].attrib['href'] == reverse(
            'devhub.submit.file', args=[self.addon.slug, latest_version.id])
        # Third back to my submissions.
        assert links[2].attrib['href'] == reverse('devhub.addons')

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
        assert links[1].attrib['href'] == reverse('devhub.addons')

        # Text is static theme specific.
        assert "This version will be available after it passes review." in (
            response.content)
        # Show the preview we started generating just after the upload step.
        imgs = content('section.addon-submission-process img')
        assert imgs[0].attrib['src'] == (
            version.previews.first().image_url)
        assert len(imgs) == 1  # Just the one preview though.

    def test_finish_submitting_unlisted_static_theme(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        # Page should be identical to extensions
        self.test_finish_submitting_unlisted_addon


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

    def setUp(self):
        super(VersionSubmitUploadMixin, self).setUp()
        self.upload = self.get_upload('extension.xpi')
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.addon.update(guid='guid@xpi')
        self.user = UserProfile.objects.get(email='del@icio.us')
        assert self.client.login(email=self.user.email)
        self.addon.versions.update(channel=self.channel)
        channel = ('listed' if self.channel == amo.RELEASE_CHANNEL_LISTED else
                   'unlisted')
        self.url = reverse('devhub.submit.version.upload',
                           args=[self.addon.slug, channel])
        assert self.addon.has_complete_metadata()
        self.version.save()

    def post(self, supported_platforms=None,
             override_validation=False, expected_status=302, source=None):
        if supported_platforms is None:
            supported_platforms = [amo.PLATFORM_MAC]
        data = {
            'upload': self.upload.uuid.hex,
            'source': source,
            'supported_platforms': [p.id for p in supported_platforms],
            'admin_override_validation': override_validation
        }
        response = self.client.post(self.url, data)
        assert response.status_code == expected_status
        return response

    def get_next_url(self, version):
        return reverse('devhub.submit.version.source', args=[
            self.addon.slug, version.pk])

    def test_missing_platforms(self):
        response = self.client.post(self.url, {'upload': self.upload.uuid.hex})
        assert response.status_code == 200
        assert response.context['new_addon_form'].errors.as_text() == (
            '* supported_platforms\n  * Need at least one platform.')

    def test_one_xpi_for_multiple_platforms(self):
        response = self.post(supported_platforms=[amo.PLATFORM_MAC,
                                                  amo.PLATFORM_LINUX])
        version = self.addon.find_latest_version(channel=self.channel)
        self.assert3xx(response, self.get_next_url(version))
        all_ = sorted([f.filename for f in version.all_files])
        assert all_ == [u'delicious_bookmarks-0.1-linux.xpi',
                        u'delicious_bookmarks-0.1-mac.xpi']

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

    def test_distribution_link(self):
        response = self.client.get(self.url)
        channel_text = ('listed' if self.channel == amo.RELEASE_CHANNEL_LISTED
                        else 'unlisted')
        distribution_url = reverse('devhub.submit.version.distribution',
                                   args=[self.addon.slug])
        doc = pq(response.content)
        assert doc('.addon-submit-distribute a').attr('href') == (
            distribution_url + '?channel=' + channel_text)

    def test_url_is_404_for_disabled_addons(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_no_redirect_for_metadata(self):
        self.addon.update(status=amo.STATUS_NULL)
        AddonCategory.objects.filter(addon=self.addon).delete()
        response = self.client.get(self.url)
        assert response.status_code == 200

    @override_switch('allow-static-theme-uploads', active=False)
    def test_static_theme_wizard_button_not_shown(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#wizardlink')

    @override_switch('allow-static-theme-uploads', active=True)
    def test_static_theme_wizard_button_not_shown_for_extensions(self):
        assert self.addon.type != amo.ADDON_STATICTHEME
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#wizardlink')

    @override_switch('allow-static-theme-uploads', active=True)
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

    @override_switch('allow-static-theme-uploads', active=True)
    def test_static_theme_wizard(self):
        channel = ('listed' if self.channel == amo.RELEASE_CHANNEL_LISTED else
                   'unlisted')
        self.addon.update(type=amo.ADDON_STATICTHEME)
        # Check we get the correct template.
        self.url = reverse('devhub.submit.version.wizard',
                           args=[self.addon.slug, channel])
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#theme-wizard')
        assert doc('#theme-wizard').attr('data-version') == '3.0'
        assert doc('input#theme-name').attr('type') == 'hidden'
        assert doc('input#theme-name').attr('value') == (
            unicode(self.addon.name))

        # And then check the upload works.
        path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip')
        self.upload = self.get_upload(abspath=path)
        response = self.post()

        version = self.addon.find_latest_version(channel=self.channel)
        assert version.channel == self.channel
        assert version.all_files[0].status == (
            amo.STATUS_AWAITING_REVIEW
            if self.channel == amo.RELEASE_CHANNEL_LISTED else
            amo.STATUS_PUBLIC)
        self.assert3xx(response, self.get_next_url(version))
        log_items = ActivityLog.objects.for_addons(self.addon)
        assert log_items.filter(action=amo.LOG.ADD_VERSION.id)
        if self.channel == amo.RELEASE_CHANNEL_LISTED:
            previews = list(version.previews.all())
            assert len(previews) == 2
            assert storage.exists(previews[0].image_path)
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

    @mock.patch('olympia.devhub.views.sign_file')
    def test_experiments_are_auto_signed(self, mock_sign_file):
        """Experiment extensions (bug 1220097) are auto-signed."""
        self.grant_permission(
            self.user, ':'.join(amo.permissions.EXPERIMENTS_SUBMIT))
        self.upload = self.get_upload(
            'telemetry_experiment.xpi',
            validation=json.dumps({
                "notices": 2, "errors": 0, "messages": [],
                "metadata": {}, "warnings": 1,
            }))
        self.addon.update(guid='experiment@xpi', status=amo.STATUS_PUBLIC)
        self.post()
        # Make sure the file created and signed is for this addon.
        assert mock_sign_file.call_count == 1
        mock_sign_file_call = mock_sign_file.call_args[0]
        signed_file = mock_sign_file_call[0]
        assert signed_file.version.addon == self.addon
        assert signed_file.version.channel == amo.RELEASE_CHANNEL_LISTED
        # There is a log for that file (with passed validation).
        log = ActivityLog.objects.latest(field_name='id')
        assert log.action == amo.LOG.EXPERIMENT_SIGNED.id

    @mock.patch('olympia.devhub.views.sign_file')
    def test_experiments_inside_webext_are_auto_signed(self, mock_sign_file):
        """Experiment extensions (bug 1220097) are auto-signed."""
        self.grant_permission(
            self.user, ':'.join(amo.permissions.EXPERIMENTS_SUBMIT))
        self.upload = self.get_upload(
            'experiment_inside_webextension.xpi',
            validation=json.dumps({
                "notices": 2, "errors": 0, "messages": [],
                "metadata": {}, "warnings": 1,
            }))
        self.addon.update(
            guid='@experiment-inside-webextension-guid',
            status=amo.STATUS_PUBLIC)
        self.post()
        # Make sure the file created and signed is for this addon.
        assert mock_sign_file.call_count == 1
        mock_sign_file_call = mock_sign_file.call_args[0]
        signed_file = mock_sign_file_call[0]
        assert signed_file.version.addon == self.addon
        assert signed_file.version.channel == amo.RELEASE_CHANNEL_LISTED
        # There is a log for that file (with passed validation).
        log = ActivityLog.objects.latest(field_name='id')
        assert log.action == amo.LOG.EXPERIMENT_SIGNED.id

    @mock.patch('olympia.devhub.views.sign_file')
    def test_experiment_upload_without_permission(self, mock_sign_file):
        self.upload = self.get_upload(
            'telemetry_experiment.xpi',
            validation=json.dumps({
                "notices": 2, "errors": 0, "messages": [],
                "metadata": {}, "warnings": 1,
            }))
        self.addon.update(guid='experiment@xpi', status=amo.STATUS_PUBLIC)

        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'You cannot submit this type of add-on')

        assert mock_sign_file.call_count == 0

    @mock.patch('olympia.devhub.views.sign_file')
    def test_experiment_inside_webext_upload_without_permission(
            self, mock_sign_file):
        self.upload = self.get_upload(
            'experiment_inside_webextension.xpi',
            validation=json.dumps({
                "notices": 2, "errors": 0, "messages": [],
                "metadata": {}, "warnings": 1,
            }))
        self.addon.update(
            guid='@experiment-inside-webextension-guid',
            status=amo.STATUS_PUBLIC)

        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'You cannot submit this type of add-on')

        assert mock_sign_file.call_count == 0

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


class TestVersionSubmitUploadUnlisted(VersionSubmitUploadMixin, UploadTest):
    channel = amo.RELEASE_CHANNEL_UNLISTED

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_success(self, mock_sign_file):
        """Sign automatically."""
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
        assert version.all_files[0].status == amo.STATUS_PUBLIC
        self.assert3xx(response, self.get_next_url(version))
        assert mock_sign_file.called

    @mock.patch('olympia.devhub.views.auto_sign_file')
    def test_one_xpi_for_multiple_platforms(self, mock_auto_sign_file):
        super(TestVersionSubmitUploadUnlisted,
              self).test_one_xpi_for_multiple_platforms()
        version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        mock_auto_sign_file.assert_has_calls([
            mock.call(f)
            for f in version.all_files])


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

        assert not self.version.approvalnotes
        assert not self.version.releasenotes

    def test_submit_success(self):
        assert all(self.get_addon().get_required_metadata())
        response = self.client.get(self.url)
        assert response.status_code == 200

        # Post and be redirected - trying to sneak in a field that shouldn't
        # be modified when this is not the first listed version.
        data = {'approvalnotes': 'approove plz',
                'releasenotes': 'loadsa stuff', 'name': 'foo'}
        response = self.client.post(self.url, data)
        self.assert3xx(
            response, reverse('devhub.submit.version.finish',
                              args=[self.addon.slug, self.version.pk]))

        # This field should not have been modified.
        assert self.get_addon().name != 'foo'

        self.version.reload()
        assert self.version.approvalnotes == 'approove plz'
        assert self.version.releasenotes == 'loadsa stuff'

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
        assert 'this should not be shown' not in response.content
        assert 'this is an info request' in response.content

    def test_dont_show_request_for_information_if_none_pending(self):
        ActivityLog.create(
            amo.LOG.REVIEWER_REPLY_VERSION, self.addon, self.version,
            user=self.user, details={'comments': 'this should not be shown'})
        ActivityLog.create(
            amo.LOG.REQUEST_INFORMATION, self.addon, self.version,
            user=self.user, details={'comments': 'this is an info request'})
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert 'this should not be shown' not in response.content
        assert 'this is an info request' not in response.content

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
        assert self.addon.status == amo.STATUS_PUBLIC
        assert not self.addon.has_complete_metadata()

        # Now, submit details for that new version, adding license. Since
        # metadata is missing, name, slug, summary and category are required to
        # be present.
        data = {
            'name': unicode(self.addon.name),
            'slug': self.addon.slug,
            'summary': unicode(self.addon.summary),

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
        assert self.addon.status == amo.STATUS_PUBLIC

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


class TestFileSubmitUpload(UploadTest):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestFileSubmitUpload, self).setUp()
        self.upload = self.get_upload('extension.xpi')
        self.addon = Addon.objects.get(id=3615)
        self.version = version_factory(
            addon=self.addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            license_id=self.addon.versions.latest().license_id,
            version='0.1',
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'platform': amo.PLATFORM_WIN.id})
        self.addon.update(guid='guid@xpi')
        assert self.client.login(email='del@icio.us')
        self.url = reverse('devhub.submit.file',
                           args=[self.addon.slug, self.version.pk])
        assert self.addon.has_complete_metadata()

    def post(self, supported_platforms=None,
             override_validation=False, expected_status=302, source=None):
        if supported_platforms is None:
            supported_platforms = [amo.PLATFORM_MAC]
        data = {
            'upload': self.upload.uuid.hex,
            'source': source,
            'supported_platforms': [p.id for p in supported_platforms],
            'admin_override_validation': override_validation
        }
        response = self.client.post(self.url, data)
        assert response.status_code == expected_status, response.content
        return response

    def test_success_listed(self):
        files_pre = self.version.all_files
        response = self.post()
        assert self.version == self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        del self.version.all_files
        files_post = self.version.all_files
        assert files_pre != files_post
        assert files_pre == files_post[:-1]
        new_file = self.version.all_files[-1]
        assert new_file.status == amo.STATUS_AWAITING_REVIEW
        assert new_file.platform == amo.PLATFORM_MAC.id
        next_url = reverse('devhub.submit.file.finish',
                           args=[self.addon.slug, self.version.pk])
        self.assert3xx(response, next_url)
        log_items = ActivityLog.objects.for_addons(self.addon)
        assert not log_items.filter(action=amo.LOG.ADD_VERSION.id).exists()

    def test_success_unlisted(self):
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        files_pre = self.version.all_files
        result = {
            'errors': 0,
            'warnings': 0,
            'notices': 2,
            'metadata': {},
            'messages': [],
        }
        FileValidation.from_json(files_pre[0], json.dumps(result))
        response = self.post()
        assert self.version == self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        del self.version.all_files
        files_post = self.version.all_files
        assert files_pre != files_post
        assert files_pre == files_post[:-1]
        new_file = self.version.all_files[-1]
        assert new_file.status == amo.STATUS_PUBLIC
        assert new_file.platform == amo.PLATFORM_MAC.id
        next_url = reverse('devhub.submit.file.finish',
                           args=[self.addon.slug, self.version.pk])
        self.assert3xx(response, next_url)
        log_items = ActivityLog.objects.for_addons(self.addon)
        assert not log_items.filter(action=amo.LOG.ADD_VERSION.id).exists()

    def test_failure_when_cant_upload_more(self):
        """e.g. when the version is already reviewed.  The button shouldn't be
        shown but upload should fail anyways."""
        self.version.all_files[0].update(status=amo.STATUS_PUBLIC)
        assert not self.version.is_allowed_upload()

        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            'You cannot upload any more files for this version.')

    def test_failure_when_version_number_doesnt_match(self):
        self.version.update(version='99')
        response = self.post(expected_status=200)
        assert pq(response.content)('ul.errorlist').text() == (
            "Version doesn't match")

    def test_with_source_ignored(self):
        # Source submit shouldn't be on the page
        response = self.client.get(self.url)
        assert not pq(response.content)('#id_source')

        # And even if submitted, should be ignored.
        tdir = temp.gettempdir()
        source = temp.NamedTemporaryFile(suffix=".zip", dir=tdir)
        source.write('a' * (2 ** 21))
        source.seek(0)
        # source should be ignored
        response = self.post(source=source)
        version = self.addon.find_latest_version(channel=self.version.channel)
        assert not version.source
        next_url = reverse('devhub.submit.file.finish',
                           args=[self.addon.slug, self.version.pk])
        self.assert3xx(response, next_url)
        assert not self.addon.reload().needs_admin_code_review
