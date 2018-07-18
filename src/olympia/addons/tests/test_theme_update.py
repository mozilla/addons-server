# -*- coding: utf-8 -*-
import json
import urllib

from StringIO import StringIO

from django.conf import settings
from django.db import connection

import mock

from services import theme_update

from olympia import amo
from olympia.addons.models import Addon, MigratedLWT
from olympia.amo.templatetags.jinja_helpers import user_media_url
from olympia.amo.tests import addon_factory, TestCase
from olympia.versions.models import Version


class TestWSGIApplication(TestCase):
    def setUp(self):
        super(TestWSGIApplication, self).setUp()
        self.environ = {'wsgi.input': StringIO()}
        self.start_response = mock.Mock()

    @mock.patch('services.theme_update.MigratedUpdate')
    @mock.patch('services.theme_update.LWThemeUpdate')
    def test_wsgi_application_200(
        self, LWThemeUpdate_mock, MigratedUpdate_mock
    ):
        urls = {
            '/themes/update-check/5': ['en-US', 5, None],
            '/en-US/themes/update-check/5': ['en-US', 5, None],
            '/fr/themes/update-check/5': ['fr', 5, None],
        }
        MigratedUpdate_mock.return_value.is_migrated = False
        # From AMO we consume the ID as the `addon_id`.
        for path_info, call_args in urls.iteritems():
            environ = dict(self.environ, PATH_INFO=path_info)
            theme_update.application(environ, self.start_response)
            LWThemeUpdate_mock.assert_called_with(*call_args)
            MigratedUpdate_mock.assert_called_with(*call_args)

        # From getpersonas.com we append `?src=gp` so we know to consume
        # the ID as the `persona_id`.
        self.environ['QUERY_STRING'] = 'src=gp'
        for path_info, call_args in urls.iteritems():
            environ = dict(self.environ, PATH_INFO=path_info)
            theme_update.application(environ, self.start_response)
            call_args[2] = 'src=gp'
            LWThemeUpdate_mock.assert_called_with(*call_args)
            MigratedUpdate_mock.assert_called_with(*call_args)
            self.start_response.assert_called_with('200 OK', mock.ANY)

    @mock.patch('services.theme_update.MigratedUpdate')
    @mock.patch('services.theme_update.LWThemeUpdate')
    def test_wsgi_application_200_migrated(
        self, LWThemeUpdate_mock, MigratedUpdate_mock
    ):
        urls = {
            '/themes/update-check/5': ['en-US', 5, None],
            '/en-US/themes/update-check/5': ['en-US', 5, None],
            '/fr/themes/update-check/5': ['fr', 5, None],
        }
        MigratedUpdate_mock.return_value.is_migrated = True
        # From AMO we consume the ID as the `addon_id`.
        for path_info, call_args in urls.iteritems():
            environ = dict(self.environ, PATH_INFO=path_info)
            theme_update.application(environ, self.start_response)
            assert not LWThemeUpdate_mock.called
            MigratedUpdate_mock.assert_called_with(*call_args)

        # From getpersonas.com we append `?src=gp` so we know to consume
        # the ID as the `persona_id`.
        self.environ['QUERY_STRING'] = 'src=gp'
        for path_info, call_args in urls.iteritems():
            environ = dict(self.environ, PATH_INFO=path_info)
            theme_update.application(environ, self.start_response)
            call_args[2] = 'src=gp'
            assert not LWThemeUpdate_mock.called
            MigratedUpdate_mock.assert_called_with(*call_args)
            self.start_response.assert_called_with('200 OK', mock.ANY)

    @mock.patch('services.theme_update.MigratedUpdate')
    @mock.patch('services.theme_update.LWThemeUpdate')
    def test_wsgi_application_404(
        self, LWThemeUpdate_mock, MigratedUpdate_mock
    ):
        urls = [
            '/xxx',
            '/themes/update-check/xxx',
            '/en-US/themes/update-check/xxx',
            '/fr/themes/update-check/xxx',
        ]

        for path_info in urls:
            environ = dict(self.environ, PATH_INFO=path_info)
            theme_update.application(environ, self.start_response)
            assert not LWThemeUpdate_mock.called
            assert not MigratedUpdate_mock.called
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
            'name': 'My Persona',
            'author': 'persona_author',
            'updateURL': (
                settings.VAMO_URL + '/en-US/themes/update-check/15663'
            ),
            'version': '0',
            'footerURL': '/15663/BCBG_Persona_footer2.png?modified=fakehash',
        }

    def check_good(self, data):
        for k, v in self.good.iteritems():
            got = data[k]
            if k.endswith('URL'):
                if k in ('detailURL', 'updateURL'):
                    assert got.startswith(
                        'http'
                    ), 'Expected absolute URL for "%s": %s' % (k, got)
                assert got.endswith(
                    v
                ), 'Expected "%s" to end with "%s". Got "%s".' % (k, v, got)

    def get_update(self, *args):
        update = theme_update.LWThemeUpdate(*args)
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
        self.check_good(json.loads(self.get_update('en-US', 15663).get_json()))

        # Testing `persona_id` from GP.
        self.good.update(
            {
                'id': '813',
                'updateURL': (
                    settings.VAMO_URL + '/en-US/themes/update-check/813?src=gp'
                ),
                'version': '1',
            }
        )

        self.check_good(
            json.loads(self.get_update('en-US', 813, 'src=gp').get_json())
        )

    def test_blank_footer_url(self):
        addon = Addon.objects.get()
        persona = addon.persona
        persona.footer = ''
        persona.save()
        data = json.loads(self.get_update('en-US', addon.pk).get_json())
        assert data['footerURL'] == ''

    def test_image_url(self):
        up = self.get_update('en-US', 15663)
        up.get_update()
        image_url = up.image_url('foo.png')
        assert user_media_url('addons') in image_url
        # Persona has no checksum, add-on modified date is used.
        assert image_url.endswith('addons/15663/foo.png?modified=1238455060')


class TestMigratedUpdate(TestCase):
    def get_update(self, *args):
        update = theme_update.MigratedUpdate(*args)
        update.cursor = connection.cursor()
        return update

    def test_is_migrated(self):
        lwt = addon_factory(type=amo.ADDON_PERSONA)
        lwt.persona.persona_id = 1234
        lwt.persona.save()
        stheme = addon_factory(type=amo.ADDON_STATICTHEME)
        assert not self.get_update('en-US', lwt.id).is_migrated
        assert not self.get_update('en-US', 1234, 'src=gp').is_migrated

        MigratedLWT.objects.create(
            lightweight_theme=lwt, static_theme=stheme, getpersonas_id=1234
        )
        assert self.get_update('en-US', lwt.id).is_migrated
        assert self.get_update('en-US', 1234, 'src=gp').is_migrated
        assert not self.get_update('en-US', lwt.id + 1).is_migrated
        assert not self.get_update('en-US', 1235, 'src=gp').is_migrated

    def test_response(self):
        lwt = addon_factory(type=amo.ADDON_PERSONA)
        lwt.persona.persona_id = 666
        lwt.persona.save()
        stheme = addon_factory(type=amo.ADDON_STATICTHEME)
        stheme.current_version.files.all()[0].update(
            filename='foo.xpi', hash='brown'
        )
        MigratedLWT.objects.create(
            lightweight_theme=lwt, static_theme=stheme, getpersonas_id=666
        )
        update = self.get_update('en-US', lwt.id)

        response = json.loads(update.get_json())
        url = '{0}{1}/{2}?{3}'.format(
            user_media_url('addons'),
            str(stheme.id),
            'foo.xpi',
            urllib.urlencode({'filehash': 'brown'}),
        )
        assert update.data == {
            'stheme_id': stheme.id,
            'filename': 'foo.xpi',
            'hash': 'brown',
        }
        assert response == {"converted_theme": {"url": url, "hash": 'brown'}}

        update = self.get_update('en-US', 666, 'src=gp')
        response = json.loads(update.get_json())
        assert update.data == {
            'stheme_id': stheme.id,
            'filename': 'foo.xpi',
            'hash': 'brown',
        }
        assert response == {"converted_theme": {"url": url, "hash": 'brown'}}
