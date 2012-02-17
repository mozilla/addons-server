# -*- coding: utf-8 -*-
import json
import os
import shutil
import sys
import traceback

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django import forms

import mock
from nose.plugins.attrib import attr
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle

import amo
import amo.tests
from addons.models import Addon
from amo.tests import assert_no_validation_errors
from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse
from applications.models import AppVersion, Application
from files.models import File, FileUpload, FileValidation
from files.tests.test_models import UploadTest as BaseUploadTest
from files.utils import parse_addon
from users.models import UserProfile
from zadmin.models import ValidationResult


class TestUploadValidation(BaseUploadTest):
    fixtures = ['base/apps', 'base/users',
                'devhub/invalid-id-uploaded-xpi.json']

    def setUp(self):
        super(TestUploadValidation, self).setUp()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

    def test_no_html_in_messages(self):
        upload = FileUpload.objects.get(name='invalid-id-20101206.xpi')
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid, 'json']))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        msg = data['validation']['messages'][0]
        eq_(msg['message'], 'The value of &lt;em:id&gt; is invalid.')
        eq_(sorted(msg['context']),
            [[u'&lt;foo/&gt;'], u'&lt;em:description&gt;...'])

    def test_date_on_upload(self):
        upload = FileUpload.objects.get(name='invalid-id-20101206.xpi')
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid]))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('td').text(), 'December  6, 2010')


class TestUploadErrors(BaseUploadTest):
    fixtures = ('base/apps', 'base/addon_3615', 'base/users')

    def setUp(self):
        super(TestUploadErrors, self).setUp()
        self.client.login(username='regular@mozilla.com',
                          password='password')

    @mock.patch.object(waffle, 'flag_is_active')
    def test_dupe_uuid(self, flag_is_active):
        flag_is_active.return_value = True
        addon = Addon.objects.get(pk=3615)
        d = parse_addon(self.get_upload('extension.xpi'))
        addon.update(guid=d['guid'])

        dupe_xpi = self.get_upload('extension.xpi')
        res = self.client.get(reverse('devhub.upload_detail',
                                      args=[dupe_xpi.uuid, 'json']))
        eq_(res.status_code, 400)
        data = json.loads(res.content)
        eq_(data['validation']['messages'],
            [{'tier': 1, 'message': 'Duplicate UUID found.',
              'type': 'error'}])
        eq_(data['validation']['ending_tier'], 1)


class TestFileValidation(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/platforms',
                'devhub/addon-validation-1']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.file_validation = FileValidation.objects.get(pk=1)
        self.file = self.file_validation.file
        self.addon = self.file.version.addon
        args = [self.addon.slug, self.file.id]
        self.url = reverse('devhub.file_validation', args=args)
        self.json_url = reverse('devhub.json_file_validation', args=args)

    def test_version_list(self):
        r = self.client.get(self.addon.get_dev_url('versions'))
        eq_(r.status_code, 200)
        a = pq(r.content)('td.file-validation a')
        eq_(a.text(), '0 errors, 0 warnings')
        eq_(a.attr('href'), self.url)

    def test_results_page(self):
        r = self.client.get(self.url, follow=True)
        eq_(r.status_code, 200)
        eq_(r.context['addon'], self.addon)
        doc = pq(r.content)
        assert not doc('#site-nav').hasClass('app-nav'), (
            'Expected add-ons devhub nav')
        eq_(doc('header h2').text(),
            u'Validation Results for searchaddon11102010-20101217.xml')
        eq_(doc('#addon-validator-suite').attr('data-validateurl'),
            self.json_url)

    def test_only_dev_can_see_results(self):
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        eq_(self.client.head(self.url, follow=True).status_code, 403)

    def test_only_dev_can_see_json_results(self):
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        eq_(self.client.head(self.json_url, follow=True).status_code, 403)

    def test_editor_can_see_results(self):
        self.client.logout()
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        eq_(self.client.head(self.url, follow=True).status_code, 200)

    def test_editor_can_see_json_results(self):
        self.client.logout()
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        eq_(self.client.head(self.json_url, follow=True).status_code, 200)

    def test_no_html_in_messages(self):
        r = self.client.post(self.json_url, follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        msg = data['validation']['messages'][0]
        eq_(msg['message'], 'The value of &lt;em:id&gt; is invalid.')
        eq_(sorted(msg['context']),
            [[u'&lt;foo/&gt;'], u'&lt;em:description&gt;...'])

    @mock.patch('files.models.File.has_been_validated')
    def test_json_results_post(self, has_been_validated):
        has_been_validated.__ne__ = mock.Mock()
        has_been_validated.__ne__.return_value = True
        eq_(self.client.post(self.json_url).status_code, 200)
        has_been_validated.__ne__.return_value = False
        eq_(self.client.post(self.json_url).status_code, 200)

    @mock.patch('files.models.File.has_been_validated')
    def test_json_results_get(self, has_been_validated):
        has_been_validated.__eq__ = mock.Mock()
        has_been_validated.__eq__.return_value = True
        eq_(self.client.get(self.json_url).status_code, 200)
        has_been_validated.__eq__.return_value = False
        eq_(self.client.get(self.json_url).status_code, 405)


class TestValidateAddon(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestValidateAddon, self).setUp()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

    def test_login_required(self):
        self.client.logout()
        r = self.client.get(reverse('devhub.validate_addon'))
        eq_(r.status_code, 302)

    def test_context(self):
        r = self.client.get(reverse('devhub.validate_addon'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#upload-addon').attr('data-upload-url'),
            reverse('devhub.standalone_upload'))


class TestValidateFile(BaseUploadTest):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615',
                'devhub/addon-file-100456', 'base/platforms']

    def setUp(self):
        super(TestValidateFile, self).setUp()
        assert self.client.login(username='del@icio.us', password='password')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.file = File.objects.get(pk=100456)
        # Move the file into place as if it were a real file
        self.file_dir = os.path.dirname(self.file.file_path)
        os.makedirs(self.file_dir)
        shutil.copyfile(self.file_path('invalid-id-20101206.xpi'),
                        self.file.file_path)
        self.addon = self.file.version.addon

    def tearDown(self):
        super(TestValidateFile, self).tearDown()
        if os.path.exists(self.file_dir):
            shutil.rmtree(self.file_dir)

    @attr('validator')
    def test_lazy_validate(self):
        r = self.client.post(reverse('devhub.json_file_validation',
                                     args=[self.addon.slug, self.file.id]),
                             follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        assert_no_validation_errors(data)
        msg = data['validation']['messages'][0]
        eq_(msg['message'], 'The value of &lt;em:id&gt; is invalid.')

    def test_time(self):
        r = self.client.post(reverse('devhub.file_validation',
                                     args=[self.addon.slug, self.file.id]),
                             follow=True)
        doc = pq(r.content)
        assert doc('time').text()

    @mock.patch.object(settings, 'EXPOSE_VALIDATOR_TRACEBACKS', False)
    @mock.patch('devhub.tasks.run_validator')
    def test_validator_errors(self, v):
        v.side_effect = ValueError('catastrophic failure in amo-validator')
        r = self.client.post(reverse('devhub.json_file_validation',
                                     args=[self.addon.slug, self.file.id]),
                             follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        eq_(data['validation'], '')
        eq_(data['error'].strip(),
            'ValueError: catastrophic failure in amo-validator')

    @mock.patch('devhub.tasks.run_validator')
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
        eq_(self.addon.binary, False)
        r = self.client.post(reverse('devhub.json_file_validation',
                                     args=[self.addon.slug, self.file.id]),
                             follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        assert_no_validation_errors(data)
        addon = Addon.objects.get(pk=self.addon.id)
        eq_(addon.binary, True)

    @mock.patch('devhub.tasks.run_validator')
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
        r = self.client.post(reverse('devhub.json_file_validation',
                                     args=[self.addon.slug, self.file.id]),
                             follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        eq_(data['validation']['ending_tier'], 5)

    @mock.patch('devhub.tasks.run_validator')
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
        eq_(self.addon.binary, False)
        r = self.client.post(reverse('devhub.json_file_validation',
                                     args=[self.addon.slug, self.file.id]),
                             follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        assert_no_validation_errors(data)
        addon = Addon.objects.get(pk=self.addon.id)
        eq_(addon.binary, True)

    @mock.patch('devhub.tasks.run_validator')
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
        r = self.client.post(reverse('devhub.json_file_validation',
                                     args=[self.addon.slug, self.file.id]),
                             follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        assert_no_validation_errors(data)
        doc = pq(data['validation']['messages'][0]['description'][0])
        eq_(doc('a').text(), 'https://bugzilla.mozilla.org/')

    @mock.patch.object(settings, 'EXPOSE_VALIDATOR_TRACEBACKS', False)
    @mock.patch('devhub.tasks.run_validator')
    def test_hide_validation_traceback(self, run_validator):
        run_validator.side_effect = RuntimeError('simulated task error')
        r = self.client.post(reverse('devhub.json_file_validation',
                                     args=[self.addon.slug, self.file.id]),
                             follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        eq_(data['validation'], '')
        eq_(data['error'], 'RuntimeError: simulated task error')

    @mock.patch.object(waffle, 'flag_is_active')
    @mock.patch('devhub.tasks.run_validator')
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
        d = parse_addon(xpi.path)
        # Set up a duplicate upload:
        addon.update(guid=d['guid'])
        res = self.client.get(reverse('devhub.validate_addon'))
        doc = pq(res.content)
        upload_url = doc('#upload-addon').attr('data-upload-url')
        with open(xpi.path, 'rb') as f:
            # Simulate JS file upload
            res = self.client.post(upload_url, {'upload': f}, follow=True)
        data = json.loads(res.content)
        # Simulate JS result polling:
        res = self.client.get(data['url'])
        data = json.loads(res.content)
        # Make sure we don't see a dupe UUID error:
        eq_(data['validation']['messages'], [])
        # Simulate JS result polling on detail page:
        res = self.client.get(data['full_report_url'], follow=True)
        res = self.client.get(res.context['validate_url'], follow=True)
        data = json.loads(res.content)
        # Again, make sure we don't see a dupe UUID error:
        eq_(data['validation']['messages'], [])


class TestCompatibilityResults(amo.tests.TestCase):
    fixtures = ['base/users', 'devhub/addon-compat-results']

    def setUp(self):
        super(TestCompatibilityResults, self).setUp()
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        self.addon = Addon.objects.get(slug='addon-compat-results')
        self.result = ValidationResult.objects.get(
                                        file__version__addon=self.addon)
        self.job = self.result.validation_job

    def validate(self, expected_status=200):
        r = self.client.post(reverse('devhub.json_bulk_compat_result',
                                     args=[self.addon.slug, self.result.id]),
                             follow=True)
        eq_(r.status_code, expected_status)
        return json.loads(r.content)

    def test_login_protected(self):
        self.client.logout()
        r = self.client.get(reverse('devhub.bulk_compat_result',
                                     args=[self.addon.slug, self.result.id]))
        eq_(r.status_code, 302)
        r = self.client.post(reverse('devhub.json_bulk_compat_result',
                                     args=[self.addon.slug, self.result.id]))
        eq_(r.status_code, 302)

    def test_target_version(self):
        r = self.client.get(reverse('devhub.bulk_compat_result',
                                    args=[self.addon.slug, self.result.id]))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        ver = json.loads(doc('.results').attr('data-target-version'))
        assert amo.FIREFOX.guid in ver, ('Unexpected: %s' % ver)
        eq_(ver[amo.FIREFOX.guid], self.job.target_version.version)

    def test_app_trans(self):
        r = self.client.get(reverse('devhub.bulk_compat_result',
                                     args=[self.addon.slug, self.result.id]))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        trans = json.loads(doc('.results').attr('data-app-trans'))
        for app in amo.APPS.values():
            eq_(trans[app.guid], app.pretty)

    def test_app_version_change_links(self):
        r = self.client.get(reverse('devhub.bulk_compat_result',
                                     args=[self.addon.slug, self.result.id]))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        trans = json.loads(doc('.results').attr('data-version-change-links'))
        eq_(trans['%s 4.0.*' % amo.FIREFOX.guid],
            'https://developer.mozilla.org/en/Firefox_4_for_developers')

    def test_validation_success(self):
        data = self.validate()
        eq_(data['validation']['messages'][3]['for_appversions'],
            {'{ec8030f7-c20a-464f-9b0e-13a3a9e97384}': ['4.0b3']})

    def test_time(self):
        r = self.client.post(reverse('devhub.bulk_compat_result',
                                     args=[self.addon.slug, self.result.id]),
                             follow=True)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        assert doc('time').text()
        eq_(doc('table tr td:eq(1)').text(), 'Firefox 4.0.*')

    @mock.patch.object(settings, 'EXPOSE_VALIDATOR_TRACEBACKS', True)
    def test_validation_error(self):
        try:
            raise RuntimeError('simulated task error')
        except:
            error = ''.join(traceback.format_exception(*sys.exc_info()))
        self.result.update(validation='', task_error=error)
        data = self.validate()
        eq_(data['validation'], '')
        eq_(data['error'], error)

    @mock.patch.object(settings, 'EXPOSE_VALIDATOR_TRACEBACKS', False)
    def test_hide_validation_traceback(self):
        try:
            raise RuntimeError('simulated task error')
        except:
            error = ''.join(traceback.format_exception(*sys.exc_info()))
        self.result.update(validation='', task_error=error)
        data = self.validate()
        eq_(data['validation'], '')
        eq_(data['error'], 'RuntimeError: simulated task error')


class TestUploadCompatCheck(BaseUploadTest):
    fixtures = ['base/apps', 'base/appversions', 'base/addon_3615']
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
        assert self.client.login(username='del@icio.us', password='password')
        self.app = Application.objects.get(pk=amo.FIREFOX.id)
        self.appver = AppVersion.objects.get(application=self.app,
                                             version='3.7a1pre')
        self.upload_url = reverse('devhub.standalone_upload')

    def poll_upload_status_url(self, upload_uuid):
        return reverse('devhub.standalone_upload_detail', args=[upload_uuid])

    def fake_xpi(self, filename=None):
        """Any useless file that has a name property (for Django)."""
        if not filename:
            filename = get_image_path('non-animated.gif')
        return open(filename, 'rb')

    def upload(self, filename=None):
        with self.fake_xpi(filename=filename) as f:
            # Simulate how JS posts data w/ app/version from the form.
            res = self.client.post(self.upload_url,
                                   {'upload': f,
                                    'app_id': self.app.pk,
                                    'version_id': self.appver.pk},
                                   follow=True)
        return json.loads(res.content)

    def test_compat_form(self):
        res = self.client.get(reverse('devhub.check_addon_compatibility'))
        eq_(res.status_code, 200)
        doc = pq(res.content)

        options = doc('#id_application option')
        expected = [(str(a.id), unicode(a.pretty)) for a in amo.APP_USAGE]
        for idx, element in enumerate(options):
            e = pq(element)
            val, text = expected[idx]
            eq_(e.val(), val)
            eq_(e.text(), text)

        eq_(doc('#upload-addon').attr('data-upload-url'), self.upload_url)
        # TODO(Kumar) actually check the form here after bug 671587

    @mock.patch('devhub.tasks.run_validator')
    def test_js_upload_validates_compatibility(self, run_validator):
        run_validator.return_value = ''  # Empty to simulate unfinished task.
        data = self.upload()
        kw = run_validator.call_args[1]
        eq_(kw['for_appversions'], {self.app.guid: [self.appver.version]})
        eq_(kw['overrides'],
            {'targetapp_minVersion': {self.app.guid: self.appver.version},
             'targetapp_maxVersion': {self.app.guid: self.appver.version}})
        eq_(data['url'], self.poll_upload_status_url(data['upload']))

    @mock.patch('devhub.tasks.run_validator')
    def test_js_poll_upload_status(self, run_validator):
        run_validator.return_value = self.compatibility_result
        data = self.upload()
        url = self.poll_upload_status_url(data['upload'])
        res = self.client.get(url)
        data = json.loads(res.content)
        if data['validation'] and data['validation']['messages']:
            raise AssertionError('Unexpected validation errors: %s'
                                 % data['validation']['messages'])

    @mock.patch('devhub.tasks.run_validator')
    def test_compat_result_report(self, run_validator):
        run_validator.return_value = self.compatibility_result
        data = self.upload()
        poll_url = self.poll_upload_status_url(data['upload'])
        res = self.client.get(poll_url)
        data = json.loads(res.content)
        res = self.client.get(data['full_report_url'])
        eq_(res.status_code, 200)
        eq_(res.context['result_type'], 'compat')
        doc = pq(res.content)
        # Shows app/version on the results page.
        eq_(doc('table tr td:eq(0)').text(), 'Firefox 3.7a1pre')
        eq_(res.context['validate_url'], poll_url)

    def test_compat_application_versions(self):
        res = self.client.get(reverse('devhub.check_addon_compatibility'))
        eq_(res.status_code, 200)
        doc = pq(res.content)
        data = {'application_id': amo.FIREFOX.id,
                'csrfmiddlewaretoken':
                            doc('input[name=csrfmiddlewaretoken]').val()}
        r = self.client.post(doc('#id_application').attr('data-url'),
                             data)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        empty = True
        for id, ver in data['choices']:
            empty = False
            eq_(AppVersion.objects.get(pk=id).version, ver)
        assert not empty, "Unexpected: %r" % data

    @mock.patch.object(waffle, 'flag_is_active')
    @mock.patch('devhub.tasks.run_validator')
    def test_rdf_parse_errors_are_ignored(self, run_validator,
                                          flag_is_active):
        run_validator.return_value = self.compatibility_result
        flag_is_active.return_value = True
        addon = Addon.objects.get(pk=3615)
        dupe_xpi = self.get_upload('extension.xpi')
        d = parse_addon(dupe_xpi)
        # Set up a duplicate upload:
        addon.update(guid=d['guid'])
        data = self.upload(filename=dupe_xpi.path)
        # Make sure we don't see a dupe UUID error:
        eq_(data['validation']['messages'], [])

    @mock.patch('devhub.tasks.run_validator')
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
        eq_(data['validation']['notices'], 1)
        eq_(data['validation']['errors'], 2)
        eq_(data['validation']['warnings'], 3)
        res = self.client.get(self.poll_upload_status_url(data['upload']))
        data = json.loads(res.content)
        eq_(data['validation']['notices'], 1)
        eq_(data['validation']['errors'], 2)
        eq_(data['validation']['warnings'], 3)

    @mock.patch('devhub.tasks.run_validator')
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
                          "tier": 1},
                         {"type": "warning",
                          "compatibility_type": None,
                          "tier": 1}],
            "metadata": {}
        })
        data = self.upload()
        eq_(data['validation']['messages'][0]['type'], 'error')
        eq_(data['validation']['messages'][1]['type'], 'warning')


class TestWebApps(amo.tests.TestCase):

    def setUp(self):
        self.webapp_path = os.path.join(os.path.dirname(__file__),
                                        'addons', 'mozball.webapp')
        self.tmp_files = []
        self.manifest = dict(name=u'Ivan Krsti\u0107', version=u'1.0',
                             description=u'summary')

    def tearDown(self):
        for tmp in self.tmp_files:
            storage.delete(tmp)

    def webapp(self, data=None, contents='', suffix='.webapp'):
        fp, tmp = tempfile.mkstemp(suffix=suffix)
        self.tmp_files.append(tmp)
        with open(tmp, 'w') as f:
            f.write(json.dumps(data) if data else contents)
        return tmp

    def test_parse(self):
        wp = WebAppParser().parse(self.webapp_path)
        eq_(wp['guid'], None)
        eq_(wp['type'], amo.ADDON_WEBAPP)
        eq_(wp['summary']['en-US'], u'Exciting Open Web development action!')
        eq_(wp['summary']['es'],
            u'\u9686Acci\u8d38n abierta emocionante del desarrollo del Web!')
        eq_(wp['summary']['it'],
            u'Azione aperta emozionante di sviluppo di fotoricettore!')
        eq_(wp['version'], '1.0')
        eq_(wp['default_locale'], 'en-US')

    def test_no_locales(self):
        wp = WebAppParser().parse(self.webapp(dict(name='foo', version='1.0',
                                                   description='summary')))
        eq_(wp['summary']['en-US'], u'summary')

    def test_no_description(self):
        wp = WebAppParser().parse(self.webapp(dict(name='foo',
                                                   version='1.0')))
        eq_(wp['summary'], {})

    def test_syntax_error(self):
        with self.assertRaises(forms.ValidationError) as exc:
            WebAppParser().parse(self.webapp(contents='}]'))
        m = exc.exception.messages[0]
        assert m.startswith('Could not parse webapp manifest'), (
                                                    'Unexpected: %s' % m)

    def test_utf8_bom(self):
        wm = codecs.BOM_UTF8 + json.dumps(self.manifest, encoding='utf8')
        wp = WebAppParser().parse(self.webapp(contents=wm))
        eq_(wp['version'], '1.0')

    def test_utf16_bom(self):
        data = json.dumps(self.manifest, encoding='utf8')
        wm = data.decode('utf8').encode('utf16')  # BOM added automatically
        wp = WebAppParser().parse(self.webapp(contents=wm))
        eq_(wp['version'], '1.0')

    def test_utf32_bom(self):
        data = json.dumps(self.manifest, encoding='utf8')
        wm = data.decode('utf8').encode('utf32')  # BOM added automatically
        wp = WebAppParser().parse(self.webapp(contents=wm))
        eq_(wp['version'], '1.0')

    def test_non_ascii(self):
        wm = json.dumps({'name': u'まつもとゆきひろ', 'version': '1.0'},
                        encoding='shift-jis')
        wp = WebAppParser().parse(self.webapp(contents=wm))
        eq_(wp['name'], {'en-US': u'まつもとゆきひろ'})
