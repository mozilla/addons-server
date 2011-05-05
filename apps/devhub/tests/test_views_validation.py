# -*- coding: utf8 -*-
import json
import os
import shutil

import mock
from nose.plugins.attrib import attr
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

from amo.tests import assert_no_validation_errors
from amo.urlresolvers import reverse
from files.models import File, FileUpload, FileValidation
from files.tests.test_models import UploadTest as BaseUploadTest
from users.models import UserProfile


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

    @mock.patch('devhub.tasks.run_validator')
    def test_validator_errors(self, v):
        v.side_effect = ValueError('catastrophic failure in amo-validator')
        r = self.client.post(reverse('devhub.json_file_validation',
                                     args=[self.addon.slug, self.file.id]),
                                     follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        eq_(data['validation'], '')
        assert data['error'].endswith(
                    "ValueError: catastrophic failure in amo-validator\n"), (
                        'Unexpected error: ...%s' % data['error'][-50:-1])
