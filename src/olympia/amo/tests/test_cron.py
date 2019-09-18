import datetime

from unittest import mock

from olympia.amo.cron import gc
from olympia.amo.tests import TestCase
from olympia.files.models import FileUpload
from olympia.lib.akismet.models import AkismetReport


@mock.patch('olympia.amo.cron.storage')
class TestGC(TestCase):
    def test_file_uploads_deletion(self, storage_mock):
        fu_new = FileUpload.objects.create(path='/tmp/new', name='new')
        fu_new.update(created=self.days_ago(6))
        fu_old = FileUpload.objects.create(path='/tmp/old', name='old')
        fu_old.update(created=self.days_ago(8))

        gc()

        assert FileUpload.objects.count() == 1
        assert storage_mock.delete.call_count == 1
        assert storage_mock.delete.call_args[0][0] == fu_old.path

    def test_file_uploads_deletion_no_path_somehow(self, storage_mock):
        fu_old = FileUpload.objects.create(path='', name='foo')
        fu_old.update(created=self.days_ago(8))

        gc()

        assert FileUpload.objects.count() == 0  # FileUpload was deleted.
        assert storage_mock.delete.call_count == 0  # No path to delete.

    def test_file_uploads_deletion_oserror(self, storage_mock):
        fu_older = FileUpload.objects.create(path='/tmp/older', name='older')
        fu_older.update(created=self.days_ago(300))
        fu_old = FileUpload.objects.create(path='/tmp/old', name='old')
        fu_old.update(created=self.days_ago(8))

        storage_mock.delete.side_effect = OSError

        gc()

        # Even though delete() caused a OSError, we still deleted the
        # FileUploads rows, and tried to delete each corresponding path on
        # the filesystem.
        assert FileUpload.objects.count() == 0
        assert storage_mock.delete.call_count == 2
        assert storage_mock.delete.call_args_list[0][0][0] == fu_older.path
        assert storage_mock.delete.call_args_list[1][0][0] == fu_old.path

    def test_akismet_reports_deletion(self, storage_mock):
        rep_new = AkismetReport.objects.create(
            comment_modified=datetime.datetime.now(),
            content_modified=datetime.datetime.now(),
            created=self.days_ago(89))
        AkismetReport.objects.create(
            comment_modified=datetime.datetime.now(),
            content_modified=datetime.datetime.now(),
            created=self.days_ago(90))

        gc()
        assert AkismetReport.objects.count() == 1
        assert AkismetReport.objects.get() == rep_new
