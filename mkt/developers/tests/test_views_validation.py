# -*- coding: utf-8 -*-
import codecs
import json
import os
import tempfile

from django import forms
from django.core.files.storage import default_storage as storage

from nose.tools import eq_

import amo
import amo.tests
from files.helpers import copyfileobj
from files.utils import WebAppParser


class TestWebApps(amo.tests.TestCase, amo.tests.AMOPaths):

    def setUp(self):
        self.webapp_path = tempfile.mktemp(suffix='.webapp')
        with storage.open(self.webapp_path, 'wb') as f:
            copyfileobj(open(os.path.join(os.path.dirname(__file__),
                                          'addons', 'mozball.webapp')),
                        f)
        self.tmp_files = []
        self.manifest = dict(name=u'Ivan Krsti\u0107', version=u'1.0',
                             description=u'summary')

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
        eq_(wp['summary']['es'],
            u'\u9686Acci\u8d38n abierta emocionante del desarrollo del Web!')
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
