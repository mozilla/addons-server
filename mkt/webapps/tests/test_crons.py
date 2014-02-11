# -*- coding: utf-8 -*-
import os
from datetime import date

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.management import call_command

import mock
from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon

import mkt
from mkt.site.fixtures import fixture
from mkt.webapps.cron import (clean_old_signed, update_app_trending,
                              update_downloads)
from mkt.webapps.models import Webapp
from mkt.webapps.tasks import _get_trending


class TestWeeklyDownloads(amo.tests.TestCase):

    def setUp(self):
        self.app = Webapp.objects.create(type=amo.ADDON_WEBAPP,
                                         status=amo.STATUS_PUBLIC)

    def get_app(self):
        return Webapp.objects.get(pk=self.app.pk)

    @mock.patch('mkt.webapps.tasks.get_monolith_client')
    def test_weekly_downloads(self, _mock):
        client = mock.Mock()
        raw = {
            'facets': {
                'installs': {
                    '_type': 'date_histogram',
                    'entries': [
                        {'count': 3,
                         'time': 1390780800000,
                         'total': 19.0},
                        {'count': 62,
                         'time': 1391385600000,
                         'total': 236.0}
                    ]
                }
            }
        }
        client.raw.return_value = raw
        _mock.return_value = client

        eq_(self.app.weekly_downloads, 0)

        update_downloads([self.app.pk])

        self.app.reload()
        eq_(self.app.weekly_downloads, 255)

    @mock.patch('mkt.webapps.tasks.get_monolith_client')
    def test_total_downloads(self, _mock):
        client = mock.Mock()
        raw = {
            'facets': {
                'installs': {
                    u'_type': u'statistical',
                    u'count': 49,
                    u'total': 6638.0
                }
            }
        }
        client.raw.return_value = raw
        _mock.return_value = client

        eq_(self.app.total_downloads, 0)

        update_downloads([self.app.pk])

        self.app.reload()
        eq_(self.app.total_downloads, 6638)

    @mock.patch('mkt.webapps.tasks.get_monolith_client')
    def test_monolith_error(self, _mock):
        client = mock.Mock()
        client.side_effect = ValueError
        client.raw.side_effect = Exception
        _mock.return_value = client

        update_downloads([self.app.pk])

        self.app.reload()
        eq_(self.app.weekly_downloads, 0)
        eq_(self.app.total_downloads, 0)


class TestCleanup(amo.tests.TestCase):

    def setUp(self):
        self.file = os.path.join(settings.SIGNED_APPS_REVIEWER_PATH,
                                 '1', 'x.z')

    def test_not_cleaned(self):
        storage.open(self.file, 'w')
        clean_old_signed()
        assert storage.exists(self.file)

    def test_cleaned(self):
        storage.open(self.file, 'w')
        clean_old_signed(-60)
        assert not storage.exists(self.file)


@mock.patch('lib.crypto.packaged.sign_app')
class TestSignApps(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.app = Addon.objects.get(id=337141)
        self.app.update(is_packaged=True)
        self.app2 = amo.tests.app_factory(
            name=u'Mozillaball ょ', app_slug='test',
            is_packaged=True, version_kw={'version': '1.0',
                                          'created': None})
        self.app3 = amo.tests.app_factory(
            name='Test app 3', app_slug='test3', status=amo.STATUS_REJECTED,
            is_packaged=True, version_kw={'version': '1.0',
                                          'created': None})

    def test_by_webapp(self, sign_mock):
        v1 = self.app.get_version()
        call_command('sign_apps', webapps=str(v1.pk))
        file1 = v1.all_files[0]
        assert sign_mock.called_with(((file1.file_path,
                                       file1.signed_file_path),))

    def test_all(self, sign_mock):
        v1 = self.app.get_version()
        v2 = self.app2.get_version()
        call_command('sign_apps')
        file1 = v1.all_files[0]
        file2 = v2.all_files[0]
        eq_(len(sign_mock.mock_calls), 2)
        eq_(sign_mock.mock_calls[0][1][:2],
            (file1.file_path, file1.signed_file_path))
        eq_(sign_mock.mock_calls[1][1][:2],
            (file2.file_path, file2.signed_file_path))


class TestUpdateTrending(amo.tests.TestCase):

    def setUp(self):
        self.app = Webapp.objects.create(type=amo.ADDON_WEBAPP,
                                         status=amo.STATUS_PUBLIC)

    @mock.patch('mkt.webapps.tasks._get_trending')
    def test_trending_saved(self, _mock):
        _mock.return_value = 12.0
        update_app_trending()

        eq_(self.app.get_trending(), 12.0)
        for region in mkt.regions.REGIONS_DICT.values():
            eq_(self.app.get_trending(region=region), 12.0)

        # Test running again updates the values as we'd expect.
        _mock.return_value = 2.0
        update_app_trending()
        eq_(self.app.get_trending(), 2.0)
        for region in mkt.regions.REGIONS_DICT.values():
            eq_(self.app.get_trending(region=region), 2.0)

    @mock.patch('mkt.webapps.tasks.get_monolith_client')
    def test_get_trending(self, _mock):
        client = mock.Mock()
        client.return_value = [
            {'count': 133.0, 'date': date(2013, 8, 26)},
            {'count': 122.0, 'date': date(2013, 9, 2)},
        ]
        _mock.return_value = client

        # 1st week count: 133 + 122 = 255
        # Prior 3 weeks get averaged: (133 + 122) / 3 = 85
        # (255 - 85) / 85 = 2.0
        eq_(_get_trending(self.app.id), 2.0)

    @mock.patch('mkt.webapps.tasks.get_monolith_client')
    def test_get_trending_threshold(self, _mock):
        client = mock.Mock()
        client.return_value = [
            {'count': 49.0, 'date': date(2013, 8, 26)},
            {'count': 50.0, 'date': date(2013, 9, 2)},
        ]
        _mock.return_value = client

        # 1st week count: 49 + 50 = 99
        # 99 is less than 100 so we return 0.0.
        eq_(_get_trending(self.app.id), 0.0)

    @mock.patch('mkt.webapps.tasks.get_monolith_client')
    def test_get_trending_monolith_error(self, _mock):
        client = mock.Mock()
        client.side_effect = ValueError
        _mock.return_value = client
        eq_(_get_trending(self.app.id), 0.0)
