# -*- coding: utf8 -*-
import json
import os
import shutil
import sys
import traceback

from django.conf import settings

import mock
from nose.plugins.attrib import attr
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

from addons.models import Addon
import amo
from amo.tests import assert_no_validation_errors
from amo.urlresolvers import reverse
from files.models import File, FileUpload, FileValidation
from files.tests.test_models import UploadTest as BaseUploadTest
from files.utils import parse_addon
from users.models import UserProfile
from zadmin.models import ValidationResult


class TestUploadValidation(BaseUploadTest):
    fixtures = ['base/apps', 'base/users',
                'devhub/invalid-id-uploaded-xpi.json']

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
    fixtures = ('base/apps', 'base/addon_3615')

    @mock.patch.object(settings, 'SHOW_UUID_ERRORS_IN_VALIDATION', True)
    def test_dupe_uuid(self):
        addon = Addon.objects.get(pk=3615)
        d = parse_addon(self.get_upload('extension.xpi').path)
        addon.update(guid=d['guid'])

        dupe_xpi = self.get_upload('extension.xpi')
        res = self.client.get(reverse('devhub.upload_detail',
                                      args=[dupe_xpi.uuid, 'json']))
        eq_(res.status_code, 400)
        data = json.loads(res.content)
        eq_(data['validation']['messages'],
            [{'tier': 1, 'message': 'Duplicate UUID found.',
              'type': 'error'}])


class TestFileValidation(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users',
                'devhub/addon-validation-1', 'base/platforms']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.file_validation = FileValidation.objects.get(pk=1)
        self.file = self.file_validation.file
        self.addon = self.file.version.addon

    def test_version_list(self):
        r = self.client.get(reverse('devhub.versions',
                            args=[self.addon.slug]))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('td.file-validation a').text(),
            '0 errors, 0 warnings')
        eq_(doc('td.file-validation a').attr('href'),
            reverse('devhub.file_validation',
                    args=[self.addon.slug, self.file.id]))

    def test_results_page(self):
        r = self.client.get(reverse('devhub.file_validation',
                                    args=[self.addon.slug, self.file.id]),
                            follow=True)
        eq_(r.status_code, 200)
        eq_(r.context['addon'], self.addon)
        doc = pq(r.content)
        eq_(doc('header h2').text(),
            u'Validation Results for searchaddon11102010-20101217.xml')
        eq_(doc('#addon-validator-suite').attr('data-validateurl'),
            reverse('devhub.json_file_validation',
                    args=[self.addon.slug, self.file.id]))

    def test_only_dev_can_see_results(self):
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        r = self.client.get(reverse('devhub.file_validation',
                                    args=[self.addon.slug, self.file.id]),
                            follow=True)
        eq_(r.status_code, 403)

    def test_only_dev_can_see_json_results(self):
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        r = self.client.post(reverse('devhub.json_file_validation',
                                    args=[self.addon.slug, self.file.id]),
                             follow=True)
        eq_(r.status_code, 403)

    def test_editor_can_see_results(self):
        self.client.logout()
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        r = self.client.get(reverse('devhub.file_validation',
                                    args=[self.addon.slug, self.file.id]),
                            follow=True)
        eq_(r.status_code, 200)

    def test_editor_can_see_json_results(self):
        self.client.logout()
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        r = self.client.post(reverse('devhub.json_file_validation',
                                    args=[self.addon.slug, self.file.id]),
                             follow=True)
        eq_(r.status_code, 200)

    def test_no_html_in_messages(self):
        r = self.client.post(reverse('devhub.json_file_validation',
                                     args=[self.addon.slug, self.file.id]),
                             follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        msg = data['validation']['messages'][0]
        eq_(msg['message'], 'The value of &lt;em:id&gt; is invalid.')
        eq_(sorted(msg['context']),
            [[u'&lt;foo/&gt;'], u'&lt;em:description&gt;...'])


class TestValidateAddon(test_utils.TestCase):
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
            reverse('devhub.upload'))


class TestValidateFile(BaseUploadTest):
    fixtures = ['base/apps', 'base/users',
                'devhub/addon-file-100456', 'base/platforms']

    def setUp(self):
        super(TestValidateFile, self).setUp()
        assert self.client.login(username='del@icio.us', password='password')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.file = File.objects.get(pk=100456)
        # Move the file into place as if it were a real file
        os.makedirs(os.path.dirname(self.file.file_path))
        shutil.copyfile(self.file_path('invalid-id-20101206.xpi'),
                        self.file.file_path)
        self.addon = self.file.version.addon

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

    @mock.patch.object(settings._wrapped, 'EXPOSE_VALIDATOR_TRACEBACKS', False)
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
    def test_validator_sets_binary_flag(self, v):
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

    @mock.patch.object(settings._wrapped, 'EXPOSE_VALIDATOR_TRACEBACKS', False)
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


class TestCompatibilityResults(test_utils.TestCase):
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
        r = self.client.post(reverse('devhub.json_validation_result',
                                     args=[self.addon.slug, self.result.id]),
                             follow=True)
        eq_(r.status_code, expected_status)
        return json.loads(r.content)

    def test_login_protected(self):
        self.client.logout()
        r = self.client.get(reverse('devhub.validation_result',
                                     args=[self.addon.slug, self.result.id]))
        eq_(r.status_code, 302)
        r = self.client.post(reverse('devhub.json_validation_result',
                                     args=[self.addon.slug, self.result.id]))
        eq_(r.status_code, 302)

    def test_target_version(self):
        r = self.client.get(reverse('devhub.validation_result',
                                    args=[self.addon.slug, self.result.id]))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        ver = json.loads(doc('.results').attr('data-target-version'))
        assert amo.FIREFOX.guid in ver, ('Unexpected: %s' % ver)
        eq_(ver[amo.FIREFOX.guid], self.job.target_version.version)

    def test_app_trans(self):
        r = self.client.get(reverse('devhub.validation_result',
                                     args=[self.addon.slug, self.result.id]))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        trans = json.loads(doc('.results').attr('data-app-trans'))
        for app in amo.APPS.values():
            eq_(trans[app.guid], app.pretty)

    def test_app_version_change_links(self):
        r = self.client.get(reverse('devhub.validation_result',
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
        r = self.client.post(reverse('devhub.validation_result',
                                     args=[self.addon.slug, self.result.id]),
                             follow=True)
        doc = pq(r.content)
        assert doc('time').text()
        eq_(doc('table tr td:eq(1)').text(), 'Firefox 4.0.*')

    @mock.patch.object(settings._wrapped, 'EXPOSE_VALIDATOR_TRACEBACKS', True)
    def test_validation_error(self):
        try:
            raise RuntimeError('simulated task error')
        except:
            error = ''.join(traceback.format_exception(*sys.exc_info()))
        self.result.update(validation='', task_error=error)
        data = self.validate()
        eq_(data['validation'], '')
        eq_(data['error'], error)

    @mock.patch.object(settings._wrapped, 'EXPOSE_VALIDATOR_TRACEBACKS', False)
    def test_hide_validation_traceback(self):
        try:
            raise RuntimeError('simulated task error')
        except:
            error = ''.join(traceback.format_exception(*sys.exc_info()))
        self.result.update(validation='', task_error=error)
        data = self.validate()
        eq_(data['validation'], '')
        eq_(data['error'], 'RuntimeError: simulated task error')
