import datetime
import os
from nose.tools import eq_

from django.conf import settings
from django.core import management

import amo.search
import amo.tests
# TODO: use DownloadCount and UpdateCount when the script is proven
# to work correctly.
from stats.models import (DownloadCountTmp as DownloadCount,
                          UpdateCountTmp as UpdateCount)


hive_folder = os.path.join(settings.ROOT, 'apps/stats/fixtures/files')


class TestADICommand(amo.tests.TestCase):
    fixtures = ('base/addon_3615',)

    def test_update_counts_from_file(self):
        management.call_command('update_counts_from_file', hive_folder,
                                date='2014-07-10')
        eq_(UpdateCount.objects.all().count(), 1)
        update_count = UpdateCount.objects.last()
        eq_(update_count.count, 5)
        eq_(update_count.date, datetime.date(2014, 7, 10))
        eq_(update_count.versions, {u'3.8': 2, u'3.7': 3})
        eq_(update_count.statuses, {u'userEnabled': 5})
        eq_(update_count.applications, {u'{app-id}': {u'30.0': 5}})
        eq_(update_count.oses, {u'WINNT': 5})
        eq_(update_count.locales, {u'en_us': 5})

    def test_download_counts_from_file(self):
        management.call_command('download_counts_from_file', hive_folder,
                                date='2014-07-10')
        eq_(DownloadCount.objects.all().count(), 1)
        download_count = DownloadCount.objects.last()
        eq_(download_count.count, 2)
        eq_(download_count.date, datetime.date(2014, 7, 10))
        eq_(download_count.sources, {u'search': 1, u'collection': 1})
