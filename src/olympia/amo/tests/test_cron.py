import os
from unittest import mock

from django.conf import settings
from django.core import mail

from olympia import amo
from olympia.amo.cron import gc, write_sitemaps
from olympia.amo.sitemap import sitemaps
from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.constants.scanners import YARA
from olympia.addons.models import Addon
from olympia.files.models import FileUpload
from olympia.scanners.models import ScannerResult


@mock.patch('olympia.amo.cron.storage')
class TestGC(TestCase):
    def test_file_uploads_deletion(self, storage_mock):
        fu_new = FileUpload.objects.create(path='/tmp/new', name='new')
        fu_new.update(created=self.days_ago(6))
        fu_old = FileUpload.objects.create(path='/tmp/old', name='old')
        fu_old.update(created=self.days_ago(16))

        gc()

        assert FileUpload.objects.count() == 1
        assert storage_mock.delete.call_count == 1
        assert storage_mock.delete.call_args[0][0] == fu_old.path

    def test_file_uploads_deletion_no_path_somehow(self, storage_mock):
        fu_old = FileUpload.objects.create(path='', name='foo')
        fu_old.update(created=self.days_ago(16))

        gc()

        assert FileUpload.objects.count() == 0  # FileUpload was deleted.
        assert storage_mock.delete.call_count == 0  # No path to delete.

    def test_file_uploads_deletion_oserror(self, storage_mock):
        fu_older = FileUpload.objects.create(path='/tmp/older', name='older')
        fu_older.update(created=self.days_ago(300))
        fu_old = FileUpload.objects.create(path='/tmp/old', name='old')
        fu_old.update(created=self.days_ago(16))

        storage_mock.delete.side_effect = OSError

        gc()

        # Even though delete() caused a OSError, we still deleted the
        # FileUploads rows, and tried to delete each corresponding path on
        # the filesystem.
        assert FileUpload.objects.count() == 0
        assert storage_mock.delete.call_count == 2
        assert storage_mock.delete.call_args_list[0][0][0] == fu_older.path
        assert storage_mock.delete.call_args_list[1][0][0] == fu_old.path

    def test_scanner_results_deletion(self, storage_mock):
        old_upload = FileUpload.objects.create(path='/tmp/old', name='old')
        old_upload.update(created=self.days_ago(16))

        new_upload = FileUpload.objects.create(path='/tmp/new', name='new')
        new_upload.update(created=self.days_ago(6))

        version = version_factory(addon=addon_factory())

        # upload = None, version = None --> DELETED
        ScannerResult.objects.create(scanner=YARA)
        # upload will become None because it is bound to an old upload, version
        # = None --> DELETED
        ScannerResult.objects.create(scanner=YARA, upload=old_upload)
        # upload is not None, version = None --> KEPT
        ScannerResult.objects.create(scanner=YARA, upload=new_upload)
        # upload = None, version is not None --> KEPT
        ScannerResult.objects.create(scanner=YARA, version=version)
        # upload is not None, version is not None --> KEPT
        ScannerResult.objects.create(scanner=YARA, upload=new_upload, version=version)

        assert ScannerResult.objects.count() == 5

        gc()

        assert ScannerResult.objects.count() == 3
        assert storage_mock.delete.call_count == 1

    def test_stale_addons_deletion(self, storage_mock):
        in_the_past = self.days_ago(16)
        to_delete = [
            Addon.objects.create(),
            Addon.objects.create(status=amo.STATUS_NULL),
            # Shouldn't be possible to have a public add-on with no versions,
            # but just in case it should still work.
            Addon.objects.create(status=amo.STATUS_APPROVED),
            Addon.objects.create(status=amo.STATUS_DELETED),
        ]
        for addon in to_delete:
            addon.update(created=in_the_past)
        to_keep = [
            Addon.objects.create(),
            Addon.objects.create(status=amo.STATUS_NULL),
            addon_factory(created=in_the_past, version_kw={'deleted': True}),
            addon_factory(created=in_the_past, status=amo.STATUS_NULL),
            addon_factory(created=in_the_past, status=amo.STATUS_DELETED),
        ]

        gc()

        for addon in to_delete:
            assert not Addon.unfiltered.filter(pk=addon.pk).exists()
        for addon in to_keep:
            assert Addon.unfiltered.filter(pk=addon.pk).exists()

        # Make sure no email was sent.
        assert len(mail.outbox) == 0


def test_write_sitemaps():
    addon_factory()
    sitemaps_dir = settings.SITEMAP_STORAGE_PATH
    assert len(os.listdir(sitemaps_dir)) == 0
    write_sitemaps()
    assert len(os.listdir(sitemaps_dir)) == (
        sum(len(sitemap.apps or ('',)) for sitemap in sitemaps.values())
        + 1  # 1 is the index
    )

    with open(os.path.join(sitemaps_dir, 'sitemap.xml')) as sitemap:
        contents = sitemap.read()
        entry = '<sitemap><loc>http://testserver/sitemap.xml?{params}</loc></sitemap>'
        for section, sitemap in sitemaps.items():
            if not sitemap.apps:
                assert entry.format(params=f'section={section}') in contents
            else:
                for app in sitemap.apps:
                    assert (
                        entry.format(
                            params=f'section={section}&amp;app_name={app.short}'
                        )
                        in contents
                    )

    with open(os.path.join(sitemaps_dir, 'sitemap-amo.xml')) as sitemap:
        contents = sitemap.read()
        assert '<url><loc>http://testserver/en-US/about</loc>' in contents

    with open(os.path.join(sitemaps_dir, 'sitemap-addons-firefox.xml')) as sitemap:
        contents = sitemap.read()
        assert '<url><loc>http://testserver/en-US/firefox/' in contents

    with open(os.path.join(sitemaps_dir, 'sitemap-addons-android.xml')) as sitemap:
        contents = sitemap.read()
        assert '<url><loc>http://testserver/en-US/android/' in contents

    with open(os.path.join(sitemaps_dir, 'sitemap-collections-firefox.xml')) as sitemap:
        contents = sitemap.read()
        assert (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n\n</urlset>' in contents
        )
