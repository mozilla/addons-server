import os
from unittest import mock

from django.conf import settings
from django.core import mail

from olympia import amo
from olympia.amo.cron import gc, write_sitemaps
from olympia.amo.sitemap import get_sitemaps
from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.constants.promoted import RECOMMENDED
from olympia.constants.scanners import YARA
from olympia.addons.models import Addon
from olympia.files.models import FileUpload
from olympia.scanners.models import ScannerResult
from olympia.amo.models import FakeEmail


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

    def test_delete_fake_emails(self, storage_mock):
        fe_old = FakeEmail.objects.create(message='This is the oldest fake email')
        fe_old.update(created=self.days_ago(360))
        fe_new = FakeEmail.objects.create(message='This is the newest fake email')
        fe_new.update(created=self.days_ago(45))

        gc()
        # FakeEmail which are older than 90 were deleted.
        assert FakeEmail.objects.count() == 1
        assert FakeEmail.objects.filter(pk=fe_new.pk).count() == 1

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


class TestWriteSitemaps(TestCase):
    def setUp(self):
        addon_factory()
        TestCase.make_addon_promoted(
            addon_factory(version_kw={'application': amo.ANDROID.id}),
            RECOMMENDED,
            approve_version=True,
        )
        assert len(os.listdir(settings.SITEMAP_STORAGE_PATH)) == 0

    def test_basic(self):
        sitemaps_dir = settings.SITEMAP_STORAGE_PATH
        write_sitemaps()
        sitemaps = get_sitemaps()
        assert len(os.listdir(sitemaps_dir)) == len(sitemaps) + 1  # 1 is the index

        with open(os.path.join(sitemaps_dir, 'sitemap.xml')) as sitemap:
            contents = sitemap.read()
            entry = (
                '<sitemap><loc>http://testserver/sitemap.xml?{params}</loc></sitemap>'
            )
            for (section, app), sitemap in sitemaps.items():
                if not app:
                    assert entry.format(params=f'section={section}') in contents
                else:
                    assert (
                        entry.format(
                            params=f'section={section}&amp;app_name={app.short}'
                        )
                        in contents
                    )
            assert (
                '<sitemap><loc>http://testserver/blog/sitemap.xml</loc></sitemap>'
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

        xml_path = os.path.join(sitemaps_dir, 'sitemap-collections-firefox.xml')
        with open(xml_path) as sitemap:
            contents = sitemap.read()
            assert (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n\n</urlset>' in contents
            )

    def test_with_args_sections(self):
        sitemaps_dir = settings.SITEMAP_STORAGE_PATH
        write_sitemaps(section='index')
        assert len(os.listdir(sitemaps_dir)) == 1
        assert os.path.exists(os.path.join(sitemaps_dir, 'sitemap.xml'))

        os.remove(os.path.join(sitemaps_dir, 'sitemap.xml'))
        write_sitemaps(section='amo')
        assert len(os.listdir(sitemaps_dir)) == 1
        assert os.path.exists(os.path.join(sitemaps_dir, 'sitemap-amo.xml'))

        os.remove(os.path.join(sitemaps_dir, 'sitemap-amo.xml'))
        write_sitemaps(section='addons')
        assert len(os.listdir(sitemaps_dir)) == 2
        assert os.path.exists(os.path.join(sitemaps_dir, 'sitemap-addons-firefox.xml'))
        assert os.path.exists(os.path.join(sitemaps_dir, 'sitemap-addons-android.xml'))

    def test_with_args_app_name(self):
        sitemaps_dir = settings.SITEMAP_STORAGE_PATH
        # typically app_name would be used in combination with a section
        write_sitemaps(section='addons', app_name='firefox')
        assert len(os.listdir(sitemaps_dir)) == 1
        assert os.path.exists(os.path.join(sitemaps_dir, 'sitemap-addons-firefox.xml'))
        os.remove(os.path.join(sitemaps_dir, 'sitemap-addons-firefox.xml'))

        # but it does work on its own, to generate all relevant sitemaps
        write_sitemaps(app_name='android')
        assert len(os.listdir(sitemaps_dir)) == 3
        assert os.path.exists(os.path.join(sitemaps_dir, 'sitemap-addons-android.xml'))
        assert os.path.exists(os.path.join(sitemaps_dir, 'sitemap-users-android.xml'))
        assert os.path.exists(os.path.join(sitemaps_dir, 'sitemap-tags-android.xml'))
