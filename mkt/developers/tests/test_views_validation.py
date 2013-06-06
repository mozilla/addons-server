# -*- coding: utf-8 -*-
import codecs
import collections
import json
import os
import tempfile

from django import forms
from django.core.files.storage import default_storage as storage

from mock import Mock, patch
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse
from files.helpers import copyfileobj
from files.models import FileUpload
from files.tests.test_models import UploadTest as BaseUploadTest
from files.utils import WebAppParser

from mkt.developers.views import standalone_hosted_upload


class TestWebApps(amo.tests.TestCase, amo.tests.AMOPaths):

    def setUp(self):
        self.webapp_path = tempfile.mktemp(suffix='.webapp')
        with storage.open(self.webapp_path, 'wb') as f:
            copyfileobj(open(os.path.join(os.path.dirname(__file__),
                                          'addons', 'mozball.webapp')),
                        f)
        self.tmp_files = []
        self.manifest = dict(name=u'Ivan Krsti\u0107', version=u'1.0',
                             description=u'summary',
                             developer=dict(name=u'Dev Namé'))

    def tearDown(self):
        for tmp in self.tmp_files:
            storage.delete(tmp)

    def webapp(self, data=None, contents='', suffix='.webapp'):
        tmp = tempfile.mktemp(suffix=suffix)
        self.tmp_files.append(tmp)
        with storage.open(tmp, 'wb') as f:
            f.write(json.dumps(data) if data else contents)
        return tmp

    def test_parse(self):
        wp = WebAppParser().parse(self.webapp_path)
        eq_(wp['guid'], None)
        eq_(wp['type'], amo.ADDON_WEBAPP)
        eq_(wp['summary']['en-US'], u'Exciting Open Web development action!')
        # UTF-8 byte string decoded to unicode.
        eq_(wp['summary']['es'],
            u'\xa1Acci\xf3n abierta emocionante del desarrollo del Web!')
        eq_(wp['summary']['it'],
            u'Azione aperta emozionante di sviluppo di fotoricettore!')
        eq_(wp['version'], '1.0')
        eq_(wp['default_locale'], 'en-US')

    def test_parse_packaged(self):
        wp = WebAppParser().parse(self.packaged_app_path('mozball.zip'))
        eq_(wp['guid'], None)
        eq_(wp['type'], amo.ADDON_WEBAPP)
        eq_(wp['name']['en-US'], u'Packaged MozillaBall ょ')
        eq_(wp['summary']['en-US'], u'Exciting Open Web development action!')
        eq_(wp['summary']['es'],
            u'¡Acción abierta emocionante del desarrollo del Web!')
        eq_(wp['summary']['it'],
            u'Azione aperta emozionante di sviluppo di fotoricettore!')
        eq_(wp['version'], '1.0')
        eq_(wp['default_locale'], 'en-US')

    def test_parse_packaged_BOM(self):
        wp = WebAppParser().parse(self.packaged_app_path('mozBOM.zip'))
        eq_(wp['guid'], None)
        eq_(wp['type'], amo.ADDON_WEBAPP)
        eq_(wp['name']['en-US'], u'Packaged MozBOM ょ')
        eq_(wp['summary']['en-US'], u'Exciting BOM action!')
        eq_(wp['summary']['es'], u'¡Acción BOM!')
        eq_(wp['summary']['it'], u'Azione BOM!')
        eq_(wp['version'], '1.0')
        eq_(wp['default_locale'], 'en-US')

    def test_no_manifest_at_root(self):
        with self.assertRaises(forms.ValidationError) as exc:
            WebAppParser().parse(
                self.packaged_app_path('no-manifest-at-root.zip'))
        m = exc.exception.messages[0]
        assert m.startswith('The file "manifest.webapp" was not found'), (
            'Unexpected: %s' % m)

    def test_no_locales(self):
        wp = WebAppParser().parse(self.webapp(dict(name='foo', version='1.0',
                                                   description='summary',
                                                   developer=dict(name='bar'))))
        eq_(wp['summary']['en-US'], u'summary')

    def test_no_description(self):
        wp = WebAppParser().parse(self.webapp(dict(name='foo',
                                                   version='1.0',
                                                   developer=dict(name='bar'))))
        eq_(wp['summary'], {})

    def test_syntax_error(self):
        with self.assertRaises(forms.ValidationError) as exc:
            WebAppParser().parse(self.webapp(contents='}]'))
        m = exc.exception.messages[0]
        assert m.startswith('The webapp manifest is not valid JSON.'), (
            'Unexpected: %s' % m)

    def test_utf8_bom(self):
        wm = codecs.BOM_UTF8 + json.dumps(self.manifest, encoding='utf8')
        wp = WebAppParser().parse(self.webapp(contents=wm))
        eq_(wp['version'], '1.0')

    def test_non_ascii(self):
        wm = json.dumps(dict(name=u'まつもとゆきひろ', version='1.0',
                             developer=dict(name=u'まつもとゆきひろ')),
                        encoding='shift-jis')
        wp = WebAppParser().parse(self.webapp(contents=wm))
        eq_(wp['name'], {'en-US': u'まつもとゆきひろ'})

    @patch('mkt.developers.views.trap_duplicate')
    def test_trap_duplicate_skipped_on_standalone(self, trap_duplicate_mock):
        self.create_switch('webapps-unique-by-domain')
        request = Mock()
        request.method = 'POST'
        request.POST = {'manifest': ''}
        request.return_value = collections.namedtuple('FakeResponse',
                                                      'status_code content')
        standalone_hosted_upload(request)
        assert not trap_duplicate_mock.called


class TestStandaloneValidation(BaseUploadTest):
    fixtures = ['base/users']

    def setUp(self):
        super(TestStandaloneValidation, self).setUp()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

        # Upload URLs
        self.hosted_upload = reverse(
            'mkt.developers.standalone_hosted_upload')
        self.packaged_upload = reverse(
            'mkt.developers.standalone_packaged_upload')

    def hosted_detail(self, uuid):
        return reverse('mkt.developers.standalone_upload_detail',
                       args=['hosted', uuid])

    def packaged_detail(self, uuid):
        return reverse('mkt.developers.standalone_upload_detail',
                       args=['packaged', uuid])

    def upload_detail(self, uuid):
        return reverse('mkt.developers.upload_detail', args=[uuid])

    def test_context(self):
        res = self.client.get(reverse('mkt.developers.validate_addon'))
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('#upload-webapp-url').attr('data-upload-url'),
            self.hosted_upload)
        eq_(doc('#upload-app').attr('data-upload-url'), self.packaged_upload)

    def detail_view(self, url_factory, upload):
        res = self.client.get(url_factory(upload.uuid))
        res_json = json.loads(res.content)
        eq_(res_json['url'], url_factory(upload.uuid))
        eq_(res_json['full_report_url'], self.upload_detail(upload.uuid))

        res = self.client.get(self.upload_detail(upload.uuid))
        eq_(res.status_code, 200)
        doc = pq(res.content)
        assert doc('header h1').text().startswith('Validation Results for ')
        suite = doc('#addon-validator-suite')

        # All apps have a `validateurl` value that corresponds to a hosted app.
        eq_(suite.attr('data-validateurl'), self.hosted_detail(upload.uuid))

    @patch('mkt.developers.tasks._fetch_manifest')
    def test_hosted_detail(self, fetch_manifest):
        def update_upload(url, upload):
            with open(os.path.join(os.path.dirname(__file__),
                                   'addons', 'mozball.webapp'), 'r') as data:
                return data.read()

        fetch_manifest.side_effect = update_upload

        res = self.client.post(
            self.hosted_upload, {'manifest': 'http://foo.bar/'}, follow=True)
        eq_(res.status_code, 200)

        uuid = json.loads(res.content)['upload']
        upload = FileUpload.objects.get(uuid=uuid)
        self.detail_view(self.hosted_detail, upload)

    def test_packaged_detail(self):
        data = open(get_image_path('animated.png'), 'rb')
        self.client.post(self.packaged_upload, {'upload': data})
        upload = FileUpload.objects.get(name='animated.png')
        self.detail_view(self.packaged_detail, upload)
