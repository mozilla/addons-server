# -*- coding: utf-8 -*-
import json

from django.core.files.storage import default_storage as storage
from django.test.utils import override_settings

from unittest import mock
import waffle

from pyquery import PyQuery as pq

from olympia import amo
from olympia.addons.models import Addon, AddonUser
from olympia.amo.tests import addon_factory, TestCase
from olympia.amo.urlresolvers import reverse
from olympia.devhub.tests.test_tasks import ValidatorTestCase
from olympia.files.models import File, FileUpload, FileValidation
from olympia.files.tests.test_models import UploadTest as BaseUploadTest
from olympia.files.utils import check_xpi_info, parse_addon
from olympia.users.models import UserProfile


class TestUploadValidation(ValidatorTestCase, BaseUploadTest):
    fixtures = ['base/users', 'devhub/invalid-id-uploaded-xpi.json']

    def setUp(self):
        super(TestUploadValidation, self).setUp()
        assert self.client.login(email='regular@mozilla.com')

    def test_only_safe_html_in_messages(self):
        upload = FileUpload.objects.get(name='invalid_webextension.xpi')
        resp = self.client.get(reverse('devhub.upload_detail',
                                       args=[upload.uuid.hex, 'json']))
        assert resp.status_code == 200
        data = json.loads(resp.content)
        msg = data['validation']['messages'][0]
        assert msg['message'] == (
            'The value of &lt;em:id&gt; is invalid. '
            'See <a href="https://mozilla.org" rel="nofollow">mozilla.org</a> '
            'for more information')
        assert msg['description'][0] == '&lt;iframe&gt;'
        assert msg['context'] == (
            [u'<em:description>...', u'<foo/>'])

    def test_date_on_upload(self):
        upload = FileUpload.objects.get(name='invalid_webextension.xpi')
        resp = self.client.get(reverse('devhub.upload_detail',
                                       args=[upload.uuid.hex]))
        assert resp.status_code == 200
        doc = pq(resp.content)
        assert doc('td').text() == 'Dec. 6, 2010'

    def test_upload_processed_validation_error(self):
        addon_file = open(
            'src/olympia/devhub/tests/addons/invalid_webextension.xpi', 'rb')
        response = self.client.post(reverse('devhub.upload'),
                                    {'name': 'addon.xpi',
                                     'upload': addon_file})
        uuid = response.url.split('/')[-2]
        upload = FileUpload.objects.get(uuid=uuid)
        assert upload.processed_validation['errors'] == 1
        assert upload.processed_validation['messages'][0]['id'] == [
            u'validator', u'unexpected_exception']

    def test_login_required(self):
        upload = FileUpload.objects.get(name='invalid_webextension.xpi')
        upload.user_id = 999
        upload.save()
        url = reverse('devhub.upload_detail', args=[upload.uuid.hex])
        assert self.client.head(url).status_code == 200

        self.client.logout()
        assert self.client.head(url).status_code == 302

    def test_no_login_required(self):
        upload = FileUpload.objects.get(name='invalid_webextension.xpi')
        self.client.logout()

        url = reverse('devhub.upload_detail', args=[upload.uuid.hex])
        assert self.client.head(url).status_code == 200


class TestUploadErrors(BaseUploadTest):
    fixtures = ('base/addon_3615', 'base/users')

    def setUp(self):
        super(TestUploadErrors, self).setUp()
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.client.login(email=self.user.email)

    @mock.patch.object(waffle, 'flag_is_active')
    def test_dupe_uuid(self, flag_is_active):
        flag_is_active.return_value = True
        addon = Addon.objects.get(pk=3615)
        data = parse_addon(self.get_upload('extension.xpi'), user=self.user)
        addon.update(guid=data['guid'])

        dupe_xpi = self.get_upload('extension.xpi')
        res = self.client.get(reverse('devhub.upload_detail',
                                      args=[dupe_xpi.uuid, 'json']))
        assert res.status_code == 400, res.content
        data = json.loads(res.content)
        assert data['validation']['messages'] == (
            [{'tier': 1, 'message': 'Duplicate add-on ID found.',
              'type': 'error', 'fatal': True}])
        assert data['validation']['ending_tier'] == 1

    def test_long_uuid(self):
        """An add-on uuid may be more than 64 chars, see bug 1203915."""
        long_guid = (u'this_guid_is_longer_than_the_limit_of_64_chars_see_'
                     u'bug_1201176_but_should_not_fail_see_bug_1203915@xpi')
        xpi_info = check_xpi_info({'guid': long_guid, 'version': '1.0'})
        assert xpi_info['guid'] == long_guid


class TestFileValidation(TestCase):
    fixtures = ['base/users', 'devhub/addon-validation-1']

    def setUp(self):
        super(TestFileValidation, self).setUp()
        assert self.client.login(email='del@icio.us')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.file_validation = FileValidation.objects.get(pk=1)
        self.file = self.file_validation.file
        with storage.open(self.file.file_path, 'wb') as f:
            f.write(b'<pretend this is an xpi>\n')
        self.addon = self.file.version.addon
        args = [self.addon.slug, self.file.id]
        self.url = reverse('devhub.file_validation', args=args)
        self.json_url = reverse('devhub.json_file_validation', args=args)

    def test_version_list(self):
        response = self.client.get(self.addon.get_dev_url('versions'))
        assert response.status_code == 200
        link = pq(response.content)('td.file-validation a')
        assert link.text() == '0 errors, 0 warnings'
        assert link.attr('href') == self.url

    def test_results_page(self):
        response = self.client.get(self.url, follow=True)
        assert response.status_code == 200
        assert response.context['addon'] == self.addon
        doc = pq(response.content)
        assert not doc('#site-nav').hasClass('app-nav'), (
            'Expected add-ons devhub nav')
        assert doc('header h2').text() == (
            u'Validation Results for testaddon-20101217.xpi')
        assert doc('#addon-validator-suite').attr('data-validateurl') == (
            self.json_url)

    def test_only_dev_can_see_results(self):
        self.client.logout()
        assert self.client.login(email='regular@mozilla.com')
        assert self.client.head(self.url, follow=True).status_code == 403

    def test_only_dev_can_see_json_results(self):
        self.client.logout()
        assert self.client.login(email='regular@mozilla.com')
        assert self.client.head(self.json_url, follow=True).status_code == 403

    def test_reviewer_can_see_results(self):
        self.client.logout()
        assert self.client.login(email='reviewer@mozilla.com')
        assert self.client.head(self.url, follow=True).status_code == 200

    def test_reviewer_can_see_json_results(self):
        self.client.logout()
        assert self.client.login(email='reviewer@mozilla.com')
        assert self.client.head(self.json_url, follow=True).status_code == 200

    def test_reviewer_cannot_see_files_not_validated(self):
        file_not_validated = File.objects.get(pk=100400)
        json_url = reverse('devhub.json_file_validation',
                           args=[self.addon.slug, file_not_validated.id])
        self.client.logout()
        assert self.client.login(email='reviewer@mozilla.com')
        assert self.client.head(json_url, follow=True).status_code == 404

    def test_developer_cant_see_results_from_other_addon(self):
        other_addon = addon_factory(users=[self.user])
        url = reverse(
            'devhub.file_validation', args=[other_addon.slug, self.file.id])
        assert self.client.get(url, follow=True).status_code == 404

    def test_developer_cant_see_json_results_from_other_addon(self):
        other_addon = addon_factory(users=[self.user])
        url = reverse(
            'devhub.json_file_validation',
            args=[other_addon.slug, self.file.id])
        assert self.client.get(url, follow=True).status_code == 404

    def test_only_safe_html_in_messages(self):
        response = self.client.post(self.json_url, follow=True)
        assert response.status_code == 200
        data = json.loads(response.content)
        msg = data['validation']['messages'][0]

        assert msg['message'] == (
            'The value of &lt;em:id&gt; is invalid. '
            'See <a href="https://mozilla.org" rel="nofollow">mozilla.org</a> '
            'for more information')
        assert msg['description'][0] == '&lt;iframe&gt;'
        assert msg['context'] == (
            [u'<em:description>...', u'<foo/>'])

    def test_cors_headers_are_sent(self):
        code_manager_url = 'https://my-code-manager-url.example.org'
        with override_settings(CODE_MANAGER_URL=code_manager_url):
            response = self.client.get(self.json_url)

        assert response['Access-Control-Allow-Origin'] == code_manager_url
        assert response['Access-Control-Allow-Methods'] == 'GET, OPTIONS'
        assert response['Access-Control-Allow-Headers'] == 'Content-Type'
        assert response['Access-Control-Allow-Credentials'] == 'true'

    def test_linkify_validation_messages(self):
        self.file_validation.update(validation=json.dumps({
            "errors": 0,
            "success": True,
            "warnings": 1,
            "notices": 0,
            "message_tree": {},
            "messages": [{
                "context": ["<code>", None],
                "description": [
                    "Something something, see https://bugzilla.mozilla.org/"],
                "column": 0,
                "line": 1,
                "file": "chrome/content/down.html",
                "tier": 2,
                "message": "Some warning",
                "type": "warning",
                "id": [],
                "uid": "bb9948b604b111e09dfdc42c0301fe38"
            }],
            "metadata": {}
        }))
        response = self.client.get(self.json_url, follow=True)
        assert response.status_code == 200
        data = json.loads(response.content)
        doc = pq(data['validation']['messages'][0]['description'][0])
        link = doc('a')[0]
        assert link.text == 'https://bugzilla.mozilla.org/'
        assert link.attrib['href'] == 'https://bugzilla.mozilla.org/'


class TestValidateAddon(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestValidateAddon, self).setUp()
        assert self.client.login(email='regular@mozilla.com')

    def test_login_required(self):
        self.client.logout()
        response = self.client.get(reverse('devhub.validate_addon'))
        assert response.status_code == 302

    def test_context_and_content(self):
        response = self.client.get(reverse('devhub.validate_addon'))
        assert response.status_code == 200

        assert b'this tool only works with legacy' not in response.content

        doc = pq(response.content)
        assert doc('#upload-addon').attr('data-upload-url') == (
            reverse('devhub.standalone_upload'))
        assert doc('#upload-addon').attr('data-upload-url-listed') == (
            reverse('devhub.standalone_upload'))
        assert doc('#upload-addon').attr('data-upload-url-unlisted') == (
            reverse('devhub.standalone_upload_unlisted'))

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_filename_not_uuidfied(self, validate_mock):
        validate_mock.return_value = json.dumps(amo.VALIDATOR_SKELETON_RESULTS)
        url = reverse('devhub.upload')

        fpath = 'src/olympia/files/fixtures/files/webextension_no_id.xpi'

        with open(fpath, 'rb') as file_:
            self.client.post(url, {'upload': file_})

        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse('devhub.upload_detail', args=(upload.uuid.hex,)))
        assert b'Validation Results for webextension_no_id' in response.content

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_upload_listed_addon(self, validate_mock):
        """Listed addons are not validated as "self-hosted" addons."""
        validate_mock.return_value = json.dumps(amo.VALIDATOR_SKELETON_RESULTS)
        url = reverse('devhub.upload')

        fpath = 'src/olympia/files/fixtures/files/webextension_no_id.xpi'

        with open(fpath, 'rb') as file_:
            self.client.post(url, {'upload': file_})

        assert (
            validate_mock.call_args[1]['channel'] ==
            amo.RELEASE_CHANNEL_LISTED)
        # No automated signing for listed add-ons.
        assert FileUpload.objects.get().automated_signing is False

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_upload_unlisted_addon(self, validate_mock):
        """Unlisted addons are validated as "self-hosted" addons."""
        validate_mock.return_value = json.dumps(amo.VALIDATOR_SKELETON_RESULTS)
        url = reverse('devhub.upload_unlisted')

        fpath = 'src/olympia/files/fixtures/files/webextension_no_id.xpi'

        with open(fpath, 'rb') as file_:
            self.client.post(url, {'upload': file_})

        assert (
            validate_mock.call_args[1]['channel'] ==
            amo.RELEASE_CHANNEL_UNLISTED)
        # Automated signing enabled for unlisted add-ons.
        assert FileUpload.objects.get().automated_signing is True


class TestUploadURLs(TestCase):
    fixtures = ('base/users',)

    def setUp(self):
        super(TestUploadURLs, self).setUp()
        user = UserProfile.objects.get(email='regular@mozilla.com')
        self.client.login(email='regular@mozilla.com')

        self.addon = Addon.objects.create(guid='thing@stuff',
                                          slug='thing-stuff',
                                          status=amo.STATUS_APPROVED)
        AddonUser.objects.create(addon=self.addon, user=user)

        self.run_addons_linter = self.patch(
            'olympia.devhub.tasks.run_addons_linter')
        self.run_addons_linter.return_value = json.dumps(
            amo.VALIDATOR_SKELETON_RESULTS)
        self.parse_addon = self.patch('olympia.devhub.utils.parse_addon')
        self.parse_addon.return_value = {
            'guid': self.addon.guid,
            'version': '1.0',
            'is_webextension': False,
        }

    def patch(self, *args, **kw):
        patcher = mock.patch(*args, **kw)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def expect_validation(self, listed, automated_signing):
        call_keywords = self.run_addons_linter.call_args[1]

        channel = (
            amo.RELEASE_CHANNEL_LISTED if listed else
            amo.RELEASE_CHANNEL_UNLISTED)

        assert call_keywords['channel'] == channel
        assert self.file_upload.automated_signing == automated_signing

    def upload(self, view, **kw):
        """Send an upload request to the given view, and save the FileUpload
        object to self.file_upload."""
        FileUpload.objects.all().delete()
        self.run_addons_linter.reset_mock()

        fpath = (
            'src/olympia/files/fixtures/files/'
            'webextension_validation_error.zip')

        with open(fpath, 'rb') as file_:
            resp = self.client.post(reverse(view, kwargs=kw),
                                    {'upload': file_})
            assert resp.status_code == 302
        self.file_upload = FileUpload.objects.get()

    def upload_addon(self, status=amo.STATUS_APPROVED, listed=True):
        """Update the test add-on with the given flags and send an upload
        request for it."""
        self.change_channel_for_addon(self.addon, listed=listed)
        self.addon.update(status=status)
        channel_text = 'listed' if listed else 'unlisted'
        return self.upload('devhub.upload_for_version',
                           channel=channel_text, addon_id=self.addon.slug)

    def test_upload_standalone(self):
        """Test that the standalone upload URLs result in file uploads with
        the correct flags."""
        self.upload('devhub.standalone_upload')
        self.expect_validation(listed=True, automated_signing=False)

        self.upload('devhub.standalone_upload_unlisted'),
        self.expect_validation(listed=False, automated_signing=True)

    def test_upload_submit(self):
        """Test that the add-on creation upload URLs result in file uploads
        with the correct flags."""
        self.upload('devhub.upload')
        self.expect_validation(listed=True, automated_signing=False)

        self.upload('devhub.upload_unlisted'),
        self.expect_validation(listed=False, automated_signing=True)

    def test_upload_addon_version(self):
        """Test that the add-on update upload URLs result in file uploads
        with the correct flags."""
        for status in amo.VALID_ADDON_STATUSES:
            self.upload_addon(listed=True, status=status)
            self.expect_validation(listed=True, automated_signing=False)

        self.upload_addon(listed=False, status=amo.STATUS_APPROVED)
        self.expect_validation(listed=False, automated_signing=True)
