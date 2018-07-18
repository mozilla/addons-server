import datetime

from datetime import timedelta

import mock

from olympia.amo.celery import task
from olympia.amo.cron import gc
from olympia.amo.tests import TestCase
from olympia.amo.utils import utc_millesecs_from_epoch
from olympia.files.models import FileUpload


fake_task_func = mock.Mock()


@task
def fake_task(**kw):
    fake_task_func()


class TestTaskTiming(TestCase):
    def setUp(self):
        patch = mock.patch('olympia.amo.celery.cache')
        self.cache = patch.start()
        self.addCleanup(patch.stop)

        patch = mock.patch('olympia.amo.celery.statsd')
        self.statsd = patch.start()
        self.addCleanup(patch.stop)

    def test_cache_start_time(self):
        fake_task.delay()
        assert self.cache.set.call_args[0][0].startswith('task_start_time')

    def test_track_run_time(self):
        minute_ago = datetime.datetime.now() - timedelta(minutes=1)
        task_start = utc_millesecs_from_epoch(minute_ago)
        self.cache.get.return_value = task_start

        fake_task.delay()

        approx_run_time = utc_millesecs_from_epoch() - task_start
        assert (
            self.statsd.timing.call_args[0][0]
            == 'tasks.olympia.amo.tests.test_cron.fake_task'
        )
        actual_run_time = self.statsd.timing.call_args[0][1]

        fuzz = 2000  # 2 seconds
        assert actual_run_time >= (
            approx_run_time - fuzz
        ) and actual_run_time <= (approx_run_time + fuzz)

        assert self.cache.get.call_args[0][0].startswith('task_start_time')
        assert self.cache.delete.call_args[0][0].startswith('task_start_time')

    def test_handle_cache_miss_for_stats(self):
        self.cache.get.return_value = None  # cache miss
        fake_task.delay()
        assert not self.statsd.timing.called


@mock.patch('olympia.amo.cron.storage')
class TestGC(TestCase):
    def test_file_uploads_deletion(self, storage_mock):
        fu_new = FileUpload.objects.create(path='/tmp/new', name='new')
        fu_new.update(created=self.days_ago(178))
        fu_old = FileUpload.objects.create(path='/tmp/old', name='old')
        fu_old.update(created=self.days_ago(181))

        gc()

        assert FileUpload.objects.count() == 1
        assert storage_mock.delete.call_count == 1
        assert storage_mock.delete.call_args[0][0] == fu_old.path

    def test_file_uploads_deletion_no_path_somehow(self, storage_mock):
        fu_old = FileUpload.objects.create(path='', name='foo')
        fu_old.update(created=self.days_ago(181))

        gc()

        assert FileUpload.objects.count() == 0  # FileUpload was deleted.
        assert storage_mock.delete.call_count == 0  # No path to delete.

    def test_file_uploads_deletion_oserror(self, storage_mock):
        fu_older = FileUpload.objects.create(path='/tmp/older', name='older')
        fu_older.update(created=self.days_ago(300))
        fu_old = FileUpload.objects.create(path='/tmp/old', name='old')
        fu_old.update(created=self.days_ago(181))

        storage_mock.delete.side_effect = OSError

        gc()

        # Even though delete() caused a OSError, we still deleted the
        # FileUploads rows, and tried to delete each corresponding path on
        # the filesystem.
        assert FileUpload.objects.count() == 0
        assert storage_mock.delete.call_count == 2
        assert storage_mock.delete.call_args_list[0][0][0] == fu_older.path
        assert storage_mock.delete.call_args_list[1][0][0] == fu_old.path
