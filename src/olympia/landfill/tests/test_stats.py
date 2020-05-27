from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase
from olympia.stats.models import DownloadCount, UpdateCount
from olympia.landfill.stats import (
    generate_download_counts,
    generate_update_counts,
)


class TestGenerateDownloadCounts(TestCase):
    def setUp(self):
        super().setUp()

        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

    def test_generate_download_counts(self):
        x_days = 10

        generate_download_counts(self.addon, x_days)

        assert DownloadCount.objects.all().count() == x_days
        download_count = DownloadCount.objects.all()[0]
        assert not download_count.sources
        download_count = DownloadCount.objects.all()[1]
        assert 'search' in download_count.sources


class TestGenerateUpdateCounts(TestCase):
    def setUp(self):
        super().setUp()

        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

    def test_generate_update_counts(self):
        x_days = 10

        generate_update_counts(self.addon, x_days)

        assert UpdateCount.objects.all().count() == x_days
        update_count = UpdateCount.objects.all()[0]
        assert 'Darwin' in update_count.oses
        assert 'en-US' in update_count.locales
