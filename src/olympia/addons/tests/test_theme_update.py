# -*- coding: utf-8 -*-
import json
import io

from unittest import mock
from urllib.parse import urlencode

from django.db import connection
from django.test.utils import override_settings

from services import theme_update

from olympia import amo
from olympia.addons.models import MigratedLWT
from olympia.amo.templatetags.jinja_helpers import user_media_url
from olympia.amo.tests import TestCase, addon_factory


class TestWSGIApplication(TestCase):

    def setUp(self):
        super(TestWSGIApplication, self).setUp()
        self.environ = {'wsgi.input': io.StringIO()}
        self.start_response = mock.Mock()
        self.urls = {
            '/themes/update-check/5': ['en-US', 5, None],
            '/en-US/themes/update-check/5': ['en-US', 5, None],
            '/fr/themes/update-check/5': ['fr', 5, None]
        }

    @mock.patch('services.theme_update.MigratedUpdate')
    @override_settings(MIGRATED_LWT_UPDATES_ENABLED=True)
    def test_wsgi_application_200_migrated(self, MigratedUpdate_mock):
        MigratedUpdate_mock.return_value.is_migrated = True
        MigratedUpdate_mock.return_value.get_json.return_value = (
            u'{"foó": "ba"}')
        # From AMO we consume the ID as the `addon_id`.
        for path_info, call_args in self.urls.items():
            environ = dict(self.environ, PATH_INFO=path_info)
            response = theme_update.application(environ, self.start_response)
            # wsgi expects a bytestring, rather than unicode response.
            assert response == [b'{"fo\xc3\xb3": "ba"}']
            MigratedUpdate_mock.assert_called_with(*call_args)
            self.start_response.assert_called_with('200 OK', mock.ANY)

        # From getpersonas.com we append `?src=gp` so we know to consume
        # the ID as the `persona_id`.
        self.environ['QUERY_STRING'] = 'src=gp'
        for path_info, call_args in self.urls.items():
            environ = dict(self.environ, PATH_INFO=path_info)
            theme_update.application(environ, self.start_response)
            call_args[2] = 'src=gp'
            MigratedUpdate_mock.assert_called_with(*call_args)
            self.start_response.assert_called_with('200 OK', mock.ANY)

    @mock.patch('services.theme_update.MigratedUpdate')
    def test_wsgi_application_404(self, MigratedUpdate_mock):
        urls = [
            '/xxx',
            '/themes/update-check/xxx',
            '/en-US/themes/update-check/xxx',
            '/fr/themes/update-check/xxx'
        ]

        for path_info in urls:
            environ = dict(self.environ, PATH_INFO=path_info)
            theme_update.application(environ, self.start_response)
            assert not MigratedUpdate_mock.called
            self.start_response.assert_called_with('404 Not Found', [])

    @mock.patch('services.theme_update.MigratedUpdate')
    @override_settings(MIGRATED_LWT_UPDATES_ENABLED=False)
    def test_404_for_migrated_but_updates_disabled(self, MigratedUpdate_mock):
        MigratedUpdate_mock.return_value.is_migrated = True
        for path_info, call_args in self.urls.items():
            environ = dict(self.environ, PATH_INFO=path_info)
            theme_update.application(environ, self.start_response)
            MigratedUpdate_mock.assert_called_with(*call_args)
            self.start_response.assert_called_with('404 Not Found', [])


class TestMigratedUpdate(TestCase):

    def get_update(self, *args):
        update = theme_update.MigratedUpdate(*args)
        update.cursor = connection.cursor()
        return update

    def test_is_migrated(self):
        stheme = addon_factory(type=amo.ADDON_STATICTHEME)
        assert not self.get_update('en-US', 666).is_migrated
        assert not self.get_update('en-US', 1234, 'src=gp').is_migrated

        MigratedLWT.objects.create(
            lightweight_theme_id=666, static_theme=stheme, getpersonas_id=1234)
        assert self.get_update('en-US', 666).is_migrated
        assert self.get_update('en-US', 1234, 'src=gp').is_migrated
        assert not self.get_update('en-US', 667).is_migrated
        assert not self.get_update('en-US', 1235, 'src=gp').is_migrated

    def test_response(self):
        stheme = addon_factory(type=amo.ADDON_STATICTHEME)
        stheme.current_version.files.all()[0].update(
            filename='foo.xpi', hash='brown')
        MigratedLWT.objects.create(
            lightweight_theme_id=999, static_theme=stheme, getpersonas_id=666)
        update = self.get_update('en-US', 999)

        response = json.loads(update.get_json())
        url = '{0}{1}/{2}?{3}'.format(
            user_media_url('addons'), str(stheme.id), 'foo.xpi',
            urlencode({'filehash': 'brown'}))
        assert update.data == {
            'stheme_id': stheme.id, 'filename': 'foo.xpi', 'hash': 'brown'}
        assert response == {
            'converted_theme': {
                'url': url,
                'hash': 'brown'
            }
        }

        update = self.get_update('en-US', 666, 'src=gp')
        response = json.loads(update.get_json())
        assert update.data == {
            'stheme_id': stheme.id, 'filename': 'foo.xpi', 'hash': 'brown'}
        assert response == {
            'converted_theme': {
                'url': url,
                'hash': 'brown'
            }
        }
