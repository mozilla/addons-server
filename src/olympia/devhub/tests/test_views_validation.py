# -*- coding: utf-8 -*-
import json

from django.core.files.storage import default_storage as storage

import mock
import waffle

from pyquery import PyQuery as pq

from olympia import amo
from olympia.addons.models import Addon, AddonUser
from olympia.amo.tests import TestCase
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import reverse
from olympia.applications.models import AppVersion
from olympia.devhub.tasks import compatibility_check
from olympia.devhub.tests.test_tasks import ValidatorTestCase
from olympia.files.models import File, FileUpload, FileValidation
from olympia.files.templatetags.jinja_helpers import copyfileobj
from olympia.files.tests.test_models import UploadTest as BaseUploadTest
from olympia.files.utils import check_xpi_info, parse_addon
from olympia.users.models import UserProfile
from olympia.zadmin.models import ValidationResult


class TestUploadValidation(ValidatorTestCase, BaseUploadTest):
    fixtures = ['base/users', 'devhub/invalid-id-uploaded-xpi.json']

    def setUp(self):
        super(TestUploadValidation, self).setUp()
        assert self.client.login(email='regular@mozilla.com')

    def test_no_html_in_messages(self):
        upload = FileUpload.objects.get(name='invalid-id-20101206.xpi')
        resp = self.client.get(reverse('devhub.upload_detail',
                                       args=[upload.uuid.hex, 'json']))
        assert resp.status_code == 200
        data = json.loads(resp.content)
        msg = data['validation']['messages'][1]
        assert msg['message'] == 'The value of &lt;em:id&gt; is invalid.'
        assert msg['description'][0] == '&lt;iframe&gt;'
        assert msg['context'] == (
            [u'<em:description>...', u'<foo/>'])

    def test_date_on_upload(self):
        upload = FileUpload.objects.get(name='invalid-id-20101206.xpi')
        resp = self.client.get(reverse('devhub.upload_detail',
                                       args=[upload.uuid.hex]))
        assert resp.status_code == 200
        doc = pq(resp.content)
        assert doc('td').text() == 'Dec. 6, 2010'

    def test_upload_processed_validation_error(self):
        addon_file = open(
            'src/olympia/files/fixtures/files/validation-error.xpi')
        response = self.client.post(reverse('devhub.upload'),
                                    {'name': 'addon.xpi',
                                     'upload': addon_file})
        uuid = response.url.split('/')[-2]
        upload = FileUpload.objects.get(uuid=uuid)
        assert upload.processed_validation['errors'] == 2
        assert upload.processed_validation['messages'][0]['id'] == [
            u'validation', u'messages', u'legacy_addons_restricted']
        assert upload.processed_validation['messages'][1]['id'] == [
            u'testcases_content', u'test_packed_packages',
            u'jar_subpackage_corrupt']

    def test_login_required(self):
        upload = FileUpload.objects.get(name='invalid-id-20101206.xpi')
        upload.user_id = 999
        upload.save()
        url = reverse('devhub.upload_detail', args=[upload.uuid.hex])
        assert self.client.head(url).status_code == 200

        self.client.logout()
        assert self.client.head(url).status_code == 302

    def test_no_login_required(self):
        upload = FileUpload.objects.get(name='invalid-id-20101206.xpi')
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
        with storage.open(self.file.file_path, 'w') as f:
            f.write('<pretend this is an xpi>\n')
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
            u'Validation Results for searchaddon11102010-20101217.xml')
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

    def test_no_html_in_messages(self):
        response = self.client.post(self.json_url, follow=True)
        assert response.status_code == 200
        data = json.loads(response.content)
        msg = data['validation']['messages'][0]
        assert msg['message'] == 'The value of &lt;em:id&gt; is invalid.'
        assert msg['description'][0] == '&lt;iframe&gt;'
        assert msg['context'] == (
            [u'<em:description>...', u'<foo/>'])

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_json_results_post_not_cached(self, validate):
        validate.return_value = json.dumps(amo.VALIDATOR_SKELETON_RESULTS)

        self.file.validation.delete()
        # Not `file.reload()`. It won't update the `validation` foreign key.
        self.file = File.objects.get(pk=self.file.pk)
        assert not self.file.has_been_validated

        assert self.client.post(self.json_url).status_code == 200
        assert validate.called

    @mock.patch('olympia.devhub.tasks.validate')
    def test_json_results_post_cached(self, validate):
        assert self.file.has_been_validated

        assert self.client.post(self.json_url).status_code == 200

        assert not validate.called

    def test_json_results_get_cached(self):
        """Test that GET requests return results when they've already been
        cached."""
        assert self.file.has_been_validated
        assert self.client.get(self.json_url).status_code == 200

    def test_json_results_get_not_cached(self):
        """Test that GET requests return a Method Not Allowed error when
        retults have not been cached."""

        self.file.validation.delete()
        # Not `file.reload()`. It won't update the `validation` foreign key.
        self.file = File.objects.get(pk=self.file.pk)
        assert not self.file.has_been_validated

        assert self.client.get(self.json_url).status_code == 405


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

        assert 'this tool only works with legacy' not in response.content

        doc = pq(response.content)
        assert doc('#upload-addon').attr('data-upload-url') == (
            reverse('devhub.standalone_upload'))
        assert doc('#upload-addon').attr('data-upload-url-listed') == (
            reverse('devhub.standalone_upload'))
        assert doc('#upload-addon').attr('data-upload-url-unlisted') == (
            reverse('devhub.standalone_upload_unlisted'))

    @mock.patch('validator.validate.validate')
    def test_filename_not_uuidfied(self, validate_mock):
        validate_mock.return_value = json.dumps(amo.VALIDATOR_SKELETON_RESULTS)
        url = reverse('devhub.upload')
        data = open(get_image_path('animated.png'), 'rb')
        self.client.post(url, {'upload': data})
        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse('devhub.upload_detail', args=(upload.uuid.hex,)))
        assert 'Validation Results for animated.png' in response.content

    @mock.patch('validator.validate.validate')
    def test_upload_listed_addon(self, validate_mock):
        """Listed addons are not validated as "self-hosted" addons."""
        validate_mock.return_value = json.dumps(amo.VALIDATOR_SKELETON_RESULTS)
        self.url = reverse('devhub.upload')
        data = open(get_image_path('animated.png'), 'rb')
        self.client.post(self.url, {'upload': data})
        # Make sure it was called with listed=True.
        assert validate_mock.call_args[1]['listed']
        # No automated signing for listed add-ons.
        assert FileUpload.objects.get().automated_signing is False

    @mock.patch('validator.validate.validate')
    def test_upload_unlisted_addon(self, validate_mock):
        """Unlisted addons are validated as "self-hosted" addons."""
        validate_mock.return_value = json.dumps(amo.VALIDATOR_SKELETON_RESULTS)
        self.url = reverse('devhub.upload_unlisted')
        data = open(get_image_path('animated.png'), 'rb')
        self.client.post(self.url, {'upload': data})
        # Make sure it was called with listed=False.
        assert not validate_mock.call_args[1]['listed']
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
                                          status=amo.STATUS_PUBLIC)
        AddonUser.objects.create(addon=self.addon, user=user)

        self.run_validator = self.patch('olympia.devhub.tasks.run_validator')
        self.run_validator.return_value = json.dumps(
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
        call_keywords = self.run_validator.call_args[1]

        assert call_keywords['listed'] == listed
        assert self.file_upload.automated_signing == automated_signing

    def upload(self, view, **kw):
        """Send an upload request to the given view, and save the FileUpload
        object to self.file_upload."""
        FileUpload.objects.all().delete()
        self.run_validator.reset_mock()

        fpath = 'src/olympia/files/fixtures/files/validation-error.xpi'

        with open(fpath) as file_:
            resp = self.client.post(reverse(view, kwargs=kw),
                                    {'upload': file_})
            assert resp.status_code == 302
        self.file_upload = FileUpload.objects.get()

    def upload_addon(self, status=amo.STATUS_PUBLIC, listed=True):
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

        self.upload_addon(listed=False, status=amo.STATUS_PUBLIC)
        self.expect_validation(listed=False, automated_signing=True)


class TestValidateFile(BaseUploadTest):
    fixtures = ['base/users', 'base/addon_3615', 'devhub/addon-file-100456']

    def setUp(self):
        super(TestValidateFile, self).setUp()
        assert self.client.login(email='del@icio.us')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.file = File.objects.get(pk=100456)
        # Move the file into place as if it were a real file
        with storage.open(self.file.file_path, 'w') as dest:
            copyfileobj(open(self.file_path('invalid-id-20101206.xpi')),
                        dest)
        self.addon = self.file.version.addon

    def tearDown(self):
        if storage.exists(self.file.file_path):
            storage.delete(self.file.file_path)
        super(TestValidateFile, self).tearDown()

    def test_lazy_validate(self):
        response = self.client.post(
            reverse('devhub.json_file_validation',
                    args=[self.addon.slug, self.file.id]), follow=True)
        assert response.status_code == 200
        data = json.loads(response.content)
        msg = data['validation']['messages'][0]
        assert 'is invalid' in msg['message']

    def test_time(self):
        response = self.client.post(
            reverse('devhub.file_validation',
                    args=[self.addon.slug, self.file.id]), follow=True)
        doc = pq(response.content)
        assert doc('time').text()

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_validator_sets_binary_flag_for_extensions(self, v):
        v.return_value = json.dumps({
            "errors": 0,
            "success": True,
            "warnings": 0,
            "notices": 0,
            "message_tree": {},
            "messages": [],
            "metadata": {
                "contains_binary_extension": True,
                "version": "1.0",
                "name": "gK0Bes Bot",
                "id": "gkobes@gkobes"
            }
        })
        assert not self.addon.binary
        response = self.client.post(
            reverse('devhub.json_file_validation',
                    args=[self.addon.slug, self.file.id]), follow=True)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert not data['validation']['errors']
        addon = Addon.objects.get(pk=self.addon.id)
        assert addon.binary

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_ending_tier_is_preserved(self, v):
        v.return_value = json.dumps({
            "errors": 0,
            "success": True,
            "warnings": 0,
            "notices": 0,
            "message_tree": {},
            "messages": [],
            "ending_tier": 5,
            "metadata": {
                "contains_binary_extension": True,
                "version": "1.0",
                "name": "gK0Bes Bot",
                "id": "gkobes@gkobes"
            }
        })
        response = self.client.post(
            reverse('devhub.json_file_validation',
                    args=[self.addon.slug, self.file.id]), follow=True)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert not data['validation']['errors']
        assert data['validation']['ending_tier'] == 5

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_validator_sets_binary_flag_for_content(self, v):
        v.return_value = json.dumps({
            "errors": 0,
            "success": True,
            "warnings": 0,
            "notices": 0,
            "message_tree": {},
            "messages": [],
            "metadata": {
                "contains_binary_content": True,
                "version": "1.0",
                "name": "gK0Bes Bot",
                "id": "gkobes@gkobes"
            }
        })
        assert not self.addon.binary
        response = self.client.post(
            reverse('devhub.json_file_validation',
                    args=[self.addon.slug, self.file.id]), follow=True)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert not data['validation']['errors']
        addon = Addon.objects.get(pk=self.addon.id)
        assert addon.binary

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_linkify_validation_messages(self, v):
        v.return_value = json.dumps({
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
        })
        response = self.client.post(
            reverse('devhub.json_file_validation',
                    args=[self.addon.slug, self.file.id]), follow=True)
        assert response.status_code == 200
        data = json.loads(response.content)
        doc = pq(data['validation']['messages'][0]['description'][0])
        assert doc('a').text() == 'https://bugzilla.mozilla.org/'

    @mock.patch.object(waffle, 'flag_is_active')
    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_rdf_parse_errors_are_ignored(self, run_validator,
                                          flag_is_active):
        run_validator.return_value = json.dumps({
            "errors": 0,
            "success": True,
            "warnings": 0,
            "notices": 0,
            "message_tree": {},
            "messages": [],
            "metadata": {}
        })
        flag_is_active.return_value = True
        addon = Addon.objects.get(pk=3615)
        xpi = self.get_upload('extension.xpi')
        data = parse_addon(xpi.path, user=self.user)
        # Set up a duplicate upload:
        addon.update(guid=data['guid'])
        res = self.client.get(reverse('devhub.validate_addon'))
        doc = pq(res.content)
        upload_url = doc('#upload-addon').attr('data-upload-url')
        with storage.open(xpi.path, 'rb') as f:
            # Simulate JS file upload
            res = self.client.post(upload_url, {'upload': f}, follow=True)
        data = json.loads(res.content)
        # Simulate JS result polling:
        res = self.client.get(data['url'])
        data = json.loads(res.content)
        # Make sure we don't see a dupe UUID error:
        assert data['validation']['messages'] == []
        # Simulate JS result polling on detail page:
        res = self.client.get(data['full_report_url'], follow=True)
        res = self.client.get(res.context['validate_url'], follow=True)
        data = json.loads(res.content)
        # Again, make sure we don't see a dupe UUID error:
        assert data['validation']['messages'] == []

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_compatibility_check(self, run_validator):
        run_validator.return_value = json.dumps({
            'errors': 0,
            'success': True,
            'warnings': 0,
            'notices': 0,
            'message_tree': {},
            'messages': [],
            'metadata': {}
        })
        upload = self.get_upload('extension.xpi')
        AppVersion.objects.create(
            application=amo.FIREFOX.id,
            version='10.0.*')

        compatibility_check(upload.pk, amo.FIREFOX.guid, '10.0.*')

        assert run_validator.call_args[1]['compat']


class TestCompatibilityResults(TestCase):
    fixtures = ['base/users', 'devhub/addon-compat-results']

    def setUp(self):
        super(TestCompatibilityResults, self).setUp()
        assert self.client.login(email='reviewer@mozilla.com')
        self.addon = Addon.objects.get(slug='addon-compat-results')
        self.result = ValidationResult.objects.get(
            file__version__addon=self.addon)
        self.job = self.result.validation_job

    def validate(self, expected_status=200):
        response = self.client.post(
            reverse('devhub.json_bulk_compat_result',
                    args=[self.addon.slug, self.result.id]), follow=True)
        assert response.status_code == expected_status
        return json.loads(response.content)

    def test_login_protected(self):
        self.client.logout()
        response = self.client.get(
            reverse('devhub.bulk_compat_result',
                    args=[self.addon.slug, self.result.id]))
        assert response.status_code == 302
        response = self.client.post(
            reverse('devhub.json_bulk_compat_result',
                    args=[self.addon.slug, self.result.id]))
        assert response.status_code == 302

    def test_target_version(self):
        response = self.client.get(
            reverse('devhub.bulk_compat_result',
                    args=[self.addon.slug, self.result.id]))
        assert response.status_code == 200
        doc = pq(response.content)
        ver = json.loads(doc('.results').attr('data-target-version'))
        assert amo.FIREFOX.guid in ver, ('Unexpected: %s' % ver)
        assert ver[amo.FIREFOX.guid] == self.job.target_version.version

    def test_app_trans(self):
        response = self.client.get(
            reverse('devhub.bulk_compat_result',
                    args=[self.addon.slug, self.result.id]))
        assert response.status_code == 200
        doc = pq(response.content)
        trans = json.loads(doc('.results').attr('data-app-trans'))
        for app in amo.APPS.values():
            assert trans[app.guid] == app.pretty

    def test_app_version_change_links(self):
        response = self.client.get(
            reverse('devhub.bulk_compat_result',
                    args=[self.addon.slug, self.result.id]))
        assert response.status_code == 200
        doc = pq(response.content)
        trans = json.loads(doc('.results').attr('data-version-change-links'))
        assert trans['%s 4.0.*' % amo.FIREFOX.guid] == (
            'https://developer.mozilla.org/en/Firefox_4_for_developers')

    def test_validation_success(self):
        data = self.validate()
        assert data['validation']['messages'][3]['for_appversions'] == (
            {'{ec8030f7-c20a-464f-9b0e-13a3a9e97384}': ['4.0b3']})

    def test_time(self):
        response = self.client.post(
            reverse('devhub.bulk_compat_result',
                    args=[self.addon.slug, self.result.id]), follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('time').text()
        assert doc('table tr td').eq(1).text() == 'Firefox 4.0.*'


class TestUploadCompatCheck(BaseUploadTest):
    fixtures = ['base/appversion', 'base/addon_3615']
    compatibility_result = json.dumps({
        "errors": 0,
        "success": True,
        "warnings": 0,
        "notices": 0,
        "compatibility_summary": {"notices": 0,
                                  "errors": 0,
                                  "warnings": 1},
        "message_tree": {},
        "messages": [],
        "metadata": {}
    })

    def setUp(self):
        super(TestUploadCompatCheck, self).setUp()
        assert self.client.login(email='del@icio.us')
        self.app = amo.FIREFOX
        self.appver = AppVersion.objects.get(application=self.app.id,
                                             version='3.7a1pre')
        self.upload_url = reverse('devhub.standalone_upload')

    def poll_upload_status_url(self, upload_uuid):
        return reverse('devhub.standalone_upload_detail', args=[upload_uuid])

    def fake_xpi(self, filename=None):
        """Any useless file that has a name property (for Django)."""
        if not filename:
            return open(get_image_path('non-animated.gif'), 'rb')
        return storage.open(filename, 'rb')

    def upload(self, filename=None):
        with self.fake_xpi(filename=filename) as f:
            # Simulate how JS posts data w/ app/version from the form.
            res = self.client.post(self.upload_url,
                                   {'upload': f,
                                    'app_id': self.app.id,
                                    'version_id': self.appver.pk},
                                   follow=True)
        return json.loads(res.content)

    def test_compat_form(self):
        res = self.client.get(reverse('devhub.check_addon_compatibility'))
        assert res.status_code == 200
        doc = pq(res.content)

        assert 'this tool only works with legacy add-ons' in res.content

        options = doc('#id_application option')
        expected = [(str(a.id), unicode(a.pretty)) for a in amo.APP_USAGE]
        for idx, element in enumerate(options):
            e = pq(element)
            val, text = expected[idx]
            assert e.val() == val
            assert e.text() == text

        assert doc('#upload-addon').attr('data-upload-url') == self.upload_url

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_js_upload_validates_compatibility(self, run_validator):
        run_validator.return_value = ''  # Empty to simulate unfinished task.
        data = self.upload()
        kw = run_validator.call_args[1]
        assert kw['for_appversions'] == {self.app.guid: [self.appver.version]}
        assert kw['overrides'] == (
            {'targetapp_minVersion': {self.app.guid: self.appver.version},
             'targetapp_maxVersion': {self.app.guid: self.appver.version}})
        assert data['url'] == self.poll_upload_status_url(data['upload'])

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_js_poll_upload_status(self, run_validator):
        run_validator.return_value = self.compatibility_result
        data = self.upload()
        url = self.poll_upload_status_url(data['upload'])
        res = self.client.get(url)
        data = json.loads(res.content)
        if data['validation'] and data['validation']['messages']:
            raise AssertionError('Unexpected validation errors: %s'
                                 % data['validation']['messages'])

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_compat_result_report(self, run_validator):
        run_validator.return_value = self.compatibility_result
        data = self.upload()
        poll_url = self.poll_upload_status_url(data['upload'])
        res = self.client.get(poll_url)
        data = json.loads(res.content)
        res = self.client.get(data['full_report_url'])
        assert res.status_code == 200
        assert res.context['result_type'] == 'compat'
        doc = pq(res.content)
        # Shows app/version on the results page.
        assert doc('table tr td:eq(0)').text() == 'Firefox 3.7a1pre'
        assert res.context['validate_url'] == poll_url

    def test_compat_application_versions(self):
        res = self.client.get(reverse('devhub.check_addon_compatibility'))
        assert res.status_code == 200
        doc = pq(res.content)
        data = {'application': amo.FIREFOX.id,
                'csrfmiddlewaretoken':
                    doc('input[name=csrfmiddlewaretoken]').val()}
        response = self.client.post(
            doc('#id_application').attr('data-url'), data)
        assert response.status_code == 200
        data = json.loads(response.content)
        empty = True
        for id, ver in data['choices']:
            empty = False
            assert AppVersion.objects.get(pk=id).version == ver
        assert not empty, "Unexpected: %r" % data

    @mock.patch.object(waffle, 'flag_is_active')
    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_rdf_parse_errors_are_ignored(self, run_validator,
                                          flag_is_active):
        run_validator.return_value = self.compatibility_result
        flag_is_active.return_value = True
        addon = Addon.objects.get(pk=3615)
        dupe_xpi = self.get_upload('extension.xpi')
        data = parse_addon(dupe_xpi, user=mock.Mock())
        # Set up a duplicate upload:
        addon.update(guid=data['guid'])
        data = self.upload(filename=dupe_xpi.path)
        # Make sure we don't see a dupe UUID error:
        assert data['validation']['messages'] == []

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_compat_summary_overrides(self, run_validator):
        run_validator.return_value = json.dumps({
            "success": True,
            "errors": 0,
            "warnings": 0,
            "notices": 0,
            "compatibility_summary": {"notices": 1,
                                      "errors": 2,
                                      "warnings": 3},
            "message_tree": {},
            "messages": [],
            "metadata": {}
        })
        data = self.upload()
        assert data['validation']['notices'] == 1
        assert data['validation']['errors'] == 2
        assert data['validation']['warnings'] == 3
        res = self.client.get(self.poll_upload_status_url(data['upload']))
        data = json.loads(res.content)
        assert data['validation']['notices'] == 1
        assert data['validation']['errors'] == 2
        assert data['validation']['warnings'] == 3

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_compat_error_type_override(self, run_validator):
        run_validator.return_value = json.dumps({
            "success": True,
            "errors": 0,
            "warnings": 0,
            "notices": 0,
            "compatibility_summary": {"notices": 0,
                                      "errors": 1,
                                      "warnings": 0},
            "message_tree": {},
            "messages": [{"type": "warning",
                          "compatibility_type": "error",
                          "message": "", "description": "",
                          "tier": 1},
                         {"type": "warning",
                          "compatibility_type": None,
                          "message": "", "description": "",
                          "tier": 1}],
            "metadata": {}
        })
        data = self.upload()
        assert data['validation']['messages'][0]['type'] == 'error'
        assert data['validation']['messages'][1]['type'] == 'warning'
