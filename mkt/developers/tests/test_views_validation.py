# -*- coding: utf8 -*-
import codecs
import json
import os
import shutil
import tempfile

from django.conf import settings
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
from amo.urlresolvers import reverse
from files.models import File, FileUpload, FileValidation
from files.tests.test_models import UploadTest as BaseUploadTest
from files.utils import parse_addon, WebAppParser
from users.models import UserProfile


class TestUploadValidation(BaseUploadTest):
    fixtures = ['base/apps', 'base/users',
                'developers/invalid-id-uploaded-xpi.json']

    def setUp(self):
        super(TestUploadValidation, self).setUp()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

    def test_no_html_in_messages(self):
        upload = FileUpload.objects.get(name='invalid-id-20101206.xpi')
        r = self.client.get(reverse('mkt.developers.upload_detail',
                                    args=[upload.uuid, 'json']))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        msg = data['validation']['messages'][0]
        eq_(msg['message'], 'The value of &lt;em:id&gt; is invalid.')
        eq_(sorted(msg['context']),
            [[u'&lt;foo/&gt;'], u'&lt;em:description&gt;...'])

    def test_date_on_upload(self):
        upload = FileUpload.objects.get(name='invalid-id-20101206.xpi')
        r = self.client.get(reverse('mkt.developers.upload_detail',
                                    args=[upload.uuid]))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.results-intro time').text(), 'December  6, 2010')


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
        res = self.client.get(reverse('mkt.developers.upload_detail',
                                      args=[dupe_xpi.uuid, 'json']))
        eq_(res.status_code, 400)
        data = json.loads(res.content)
        eq_(data['validation']['messages'],
            [{'tier': 1, 'message': 'Duplicate UUID found.',
              'type': 'error'}])
        eq_(data['validation']['ending_tier'], 1)


class TestFileValidation(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/platforms',
                'developers/addon-validation-1']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.file_validation = FileValidation.objects.get(pk=1)
        self.file = self.file_validation.file
        self.addon = self.file.version.addon
        self.addon.update(app_slug=self.addon.slug, type=amo.ADDON_WEBAPP)
        self.url = self.addon.get_dev_url('file_validation', [self.file.id])
        self.json_url = self.addon.get_dev_url('json_file_validation',
                                               [self.file.id])

    def test_app_results_page(self):
        r = self.client.get(self.url, follow=True)
        eq_(r.status_code, 200)
        eq_(r.context['addon'].id, self.addon.id)

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


#class TestValidateAddon(amo.tests.TestCase):
#    fixtures = ['base/users']
#
#    def setUp(self):
#        super(TestValidateAddon, self).setUp()
#        assert self.client.login(username='regular@mozilla.com',
#                                 password='password')
#
#    def test_login_required(self):
#        self.client.logout()
#        r = self.client.get(reverse('mkt.developers.validate_addon'))
#        eq_(r.status_code, 302)
#
#    def test_context(self):
#        r = self.client.get(reverse('mkt.developers.validate_addon'))
#        eq_(r.status_code, 200)
#        doc = pq(r.content)
#        eq_(doc('#upload-addon').attr('data-upload-url'),
#            reverse('mkt.developers.standalone_upload'))


class TestValidateFile(BaseUploadTest):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615',
                'developers/addon-file-100456', 'base/platforms']

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
        self.addon.update(app_slug=self.addon.slug, type=amo.ADDON_WEBAPP)
        self.url = self.addon.get_dev_url('file_validation', [self.file.id])
        self.json_url = self.addon.get_dev_url('json_file_validation',
                                               [self.file.id])

    def tearDown(self):
        super(TestValidateFile, self).tearDown()
        if os.path.exists(self.file_dir):
            shutil.rmtree(self.file_dir)

    @attr('validator')
    def test_lazy_validate(self):
        r = self.client.post(self.json_url,
                             follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        assert_no_validation_errors(data)
        msg = data['validation']['messages'][0]
        eq_(msg['message'], 'The value of &lt;em:id&gt; is invalid.')

    def test_time(self):
        r = self.client.post(self.url, follow=True)
        doc = pq(r.content)
        assert doc('time').text()

    @mock.patch.object(settings, 'EXPOSE_VALIDATOR_TRACEBACKS', False)
    @mock.patch('mkt.developers.tasks.run_validator')
    def test_validator_errors(self, v):
        v.side_effect = ValueError('catastrophic failure in amo-validator')
        r = self.client.post(self.json_url, follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        eq_(data['validation'], '')
        eq_(data['error'].strip(),
            'ValueError: catastrophic failure in amo-validator')

    @mock.patch('mkt.developers.tasks.run_validator')
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
        r = self.client.post(self.json_url, follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        assert_no_validation_errors(data)
        doc = pq(data['validation']['messages'][0]['description'][0])
        eq_(doc('a').text(), 'https://bugzilla.mozilla.org/')

    @mock.patch.object(settings, 'EXPOSE_VALIDATOR_TRACEBACKS', False)
    @mock.patch('mkt.developers.tasks.run_validator')
    def test_hide_validation_traceback(self, run_validator):
        run_validator.side_effect = RuntimeError('simulated task error')
        r = self.client.post(self.json_url, follow=True)
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        eq_(data['validation'], '')
        eq_(data['error'], 'RuntimeError: simulated task error')


class TestWebApps(amo.tests.TestCase):

    def setUp(self):
        self.webapp_path = os.path.join(os.path.dirname(__file__),
                                        'addons', 'mozball.webapp')
        self.tmp_files = []
        self.manifest = dict(name=u'Ivan Krsti\u0107', version=u'1.0',
                             description=u'summary')

    def tearDown(self):
        for tmp in self.tmp_files:
            os.unlink(tmp)

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
