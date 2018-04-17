# -*- coding: utf-8 -*-
import json

from StringIO import StringIO

from django.conf import settings
from django.db import connection

import mock

from services import theme_update

from olympia.addons.models import Addon
from olympia.amo.templatetags.jinja_helpers import (
    user_media_path, user_media_url)
from olympia.amo.tests import TestCase
from olympia.versions.models import Version


class TestWSGIApplication(TestCase):

    def setUp(self):
        super(TestWSGIApplication, self).setUp()
        self.environ = {'wsgi.input': StringIO()}
        self.start_response = mock.Mock()

    @mock.patch('services.theme_update.ThemeUpdate')
    def test_wsgi_application_200(self, ThemeUpdate_mock):
        urls = {
            '/themes/update-check/5': ['en-US', 5, None],
            '/en-US/themes/update-check/5': ['en-US', 5, None],
            '/fr/themes/update-check/5': ['fr', 5, None]
        }

        # From AMO we consume the ID as the `addon_id`.
        for path_info, call_args in urls.iteritems():
            environ = dict(self.environ, PATH_INFO=path_info)
            theme_update.application(environ, self.start_response)
            ThemeUpdate_mock.assert_called_with(*call_args)

        # From getpersonas.com we append `?src=gp` so we know to consume
        # the ID as the `persona_id`.
        self.environ['QUERY_STRING'] = 'src=gp'
        for path_info, call_args in urls.iteritems():
            environ = dict(self.environ, PATH_INFO=path_info)
            theme_update.application(environ, self.start_response)
            call_args[2] = 'src=gp'
            ThemeUpdate_mock.assert_called_with(*call_args)
            self.start_response.assert_called_with('200 OK', mock.ANY)

    @mock.patch('services.theme_update.ThemeUpdate')
    def test_wsgi_application_404(self, ThemeUpdate_mock):
        urls = [
            '/xxx',
            '/themes/update-check/xxx',
            '/en-US/themes/update-check/xxx',
            '/fr/themes/update-check/xxx'
        ]

        for path_info in urls:
            environ = dict(self.environ, PATH_INFO=path_info)
            theme_update.application(environ, self.start_response)
            assert not ThemeUpdate_mock.called
            self.start_response.assert_called_with('404 Not Found', [])


class TestThemeUpdate(TestCase):
    fixtures = ['addons/persona']

    def setUp(self):
        super(TestThemeUpdate, self).setUp()
        self.good = {
            'username': 'persona_author',
            'description': 'yolo',
            'detailURL': '/en-US/addon/a15663/',
            'accentcolor': '#8d8d97',
            'iconURL': '/15663/preview_small.jpg?modified=fakehash',
            'previewURL': '/15663/preview.jpg?modified=fakehash',
            'textcolor': '#ffffff',
            'id': '15663',
            'headerURL': '/15663/BCBG_Persona_header2.png?modified=fakehash',
            'dataurl': '',
            'name': 'My Persona',
            'author': 'persona_author',
            'updateURL': (settings.VAMO_URL +
                          '/en-US/themes/update-check/15663'),
            'version': '0',
            'footerURL': '/15663/BCBG_Persona_footer2.png?modified=fakehash'
        }

    def check_good(self, data):
        for k, v in self.good.iteritems():
            got = data[k]
            if k.endswith('URL'):
                if k in ('detailURL', 'updateURL'):
                    assert got.startswith('http'), (
                        'Expected absolute URL for "%s": %s' % (k, got))
                assert got.endswith(v), (
                    'Expected "%s" to end with "%s". Got "%s".' % (
                        k, v, got))

    def get_update(self, *args):
        update = theme_update.ThemeUpdate(*args)
        update.cursor = connection.cursor()
        return update

    def test_get_json_bad_ids(self):
        assert self.get_update('en-US', 999).get_json() is None
        assert self.get_update('en-US', 813).get_json() is None

    def test_get_json_good_ids(self):
        addon = Addon.objects.get()
        addon.summary = 'yolo'
        addon._current_version = Version.objects.get()
        addon.save()
        addon.persona.checksum = 'fakehash'
        addon.persona.save()
        addon.increment_theme_version_number()

        # Testing `addon_id` from AMO.
        self.check_good(
            json.loads(self.get_update('en-US', 15663).get_json()))

        # Testing `persona_id` from GP.
        self.good.update({
            'id': '813',
            'updateURL': (settings.VAMO_URL +
                          '/en-US/themes/update-check/813?src=gp'),
            'version': '1'
        })

        self.check_good(
            json.loads(self.get_update('en-US', 813, 'src=gp').get_json()))

    def test_get_json_missing_colors(self):
        addon = Addon.objects.get()
        addon.persona.textcolor = None
        addon.persona.accentcolor = None
        addon.persona.save()
        data = json.loads(self.get_update('en-US', addon.pk).get_json())
        assert data['textcolor'] == '#'
        assert data['accentcolor'] == '#'

    def test_blank_footer_url(self):
        addon = Addon.objects.get()
        persona = addon.persona
        persona.footer = ''
        persona.save()
        data = json.loads(self.get_update('en-US', addon.pk).get_json())
        assert data['footerURL'] == ''

    def test_image_path(self):
        up = self.get_update('en-US', 15663)
        up.get_update()
        image_path = up.image_path('foo.png')
        assert user_media_path('addons') in image_path

    def test_image_url(self):
        up = self.get_update('en-US', 15663)
        up.get_update()
        image_url = up.image_url('foo.png')
        assert user_media_url('addons') in image_url
        # Persona has no checksum, add-on modified date is used.
        assert image_url.endswith('addons/15663/foo.png?modified=1238455060')
