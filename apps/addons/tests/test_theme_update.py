# -*- coding: utf-8 -*-
import json
from StringIO import StringIO

from django.conf import settings
from django.db import connection

import mock
from nose.tools import eq_

import amo.tests
from addons.models import Addon
from services import theme_update


class TestWSGIApplication(amo.tests.TestCase):

    def setUp(self):
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


class TestThemeUpdate(amo.tests.TestCase):
    fixtures = ['addons/persona']
    good = {
        'username': 'persona_author',
        'description': 'yolo',
        'detailURL': settings.SITE_URL + '/en-US/addon/a15663/',
        'accentcolor': '#8d8d97',
        'iconURL': '/15663/preview_small.jpg',
        'previewURL': '/15663/preview.jpg',
        'textcolor': '#ffffff',
        'id': '15663',
        'headerURL': '/15663/BCBG_Persona_header2.png',
        'dataurl': '',
        'name': 'My Persona',
        'author': 'persona_author',
        'updateURL': settings.VAMO_URL + '/en-US/themes/update-check/15663',
        'version': '1.0',
        'footerURL': '/15663/BCBG_Persona_footer2.png'
    }

    def check_good(self, data):
        for k, v in self.good.iteritems():
            got = data[k]
            if k.endswith('URL'):
                if k in ('detailURL', 'updateURL'):
                    eq_(got.find('?'), -1,
                        '"%s" should not contain "?"' % k)
                else:
                    assert got.find('?') > -1, (
                        '"%s" must contain "?" for modified timestamp' % k)

                # Strip `?<modified>` timestamps.
                got = got.rsplit('?')[0]

                assert got.endswith(v), (
                    'Expected "%s" to end with "%s". Got "%s".' % (k, v, got))
            else:
                eq_(got, v, 'Expected "%s" for "%s". Got "%s".' % (v, k, got))

    def get_update(self, *args):
        update = theme_update.ThemeUpdate(*args)
        update.cursor = connection.cursor()
        return update

    def test_get_json_bad_ids(self):
        eq_(self.get_update('en-US', 999).get_json(), None)
        eq_(self.get_update('en-US', 813).get_json(), None)

    def test_get_json_good_ids(self):
        self.addon = Addon.objects.get()
        self.addon.summary = 'yolo'
        self.addon.save()

        # Testing `addon_id` from AMO.
        self.check_good(
            json.loads(self.get_update('en-US', 15663).get_json()))

        # Testing `persona_id` from GP.
        self.check_good(
            json.loads(self.get_update('en-US', 813, 'src=gp').get_json()))
