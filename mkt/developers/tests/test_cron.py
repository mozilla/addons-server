import mock
from nose.tools import eq_

import amo.tests
from addons.models import Addon

import mkt
from mkt.developers.cron import exclude_new_region, send_new_region_emails
from mkt.developers.tasks import convert_purified
from mkt.webapps.models import AddonExcludedRegion


class TestPurify(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)

    def test_no_html(self):
        self.addon.the_reason = 'foo'
        self.addon.save()
        last = Addon.objects.get(pk=3615).modified
        convert_purified([self.addon.pk])
        addon = Addon.objects.get(pk=3615)
        eq_(addon.modified, last)

    def test_has_html(self):
        self.addon.the_reason = 'foo <script>foo</script>'
        self.addon.save()
        convert_purified([self.addon.pk])
        addon = Addon.objects.get(pk=3615)
        assert addon.the_reason.localized_string_clean


class TestSendNewRegionEmails(amo.tests.WebappTestCase):

    @mock.patch('mkt.developers.cron._region_email')
    def test_called(self, _region_email_mock):
        send_new_region_emails([mkt.regions.CA])
        eq_(list(_region_email_mock.call_args_list[0][0][0]),
            [self.app.id])

    @mock.patch('mkt.developers.cron._region_email')
    def test_not_called_with_exclusions(self, _region_email_mock):
        AddonExcludedRegion.objects.create(addon=self.app,
            region=mkt.regions.CA.id)
        send_new_region_emails([mkt.regions.CA])
        eq_(list(_region_email_mock.call_args_list[0][0][0]), [])

    @mock.patch('mkt.developers.cron._region_email')
    def test_not_called_with_future_exclusions(self, _region_email_mock):
        AddonExcludedRegion.objects.create(addon=self.app,
            region=mkt.regions.FUTURE.id)
        send_new_region_emails([mkt.regions.CA])
        eq_(list(_region_email_mock.call_args_list[0][0][0]), [])


class TestExcludeNewRegion(amo.tests.WebappTestCase):

    @mock.patch('mkt.developers.cron._region_exclude')
    def test_not_called_by_default(self, _region_exclude_mock):
        exclude_new_region([mkt.regions.CA])
        eq_(list(_region_exclude_mock.call_args_list[0][0][0]),
            [])

    @mock.patch('mkt.developers.cron._region_exclude')
    def test_not_called_with_ordinary_exclusions(self, _region_exclude_mock):
        AddonExcludedRegion.objects.create(addon=self.app,
            region=mkt.regions.CA.id)
        exclude_new_region([mkt.regions.CA])
        eq_(list(_region_exclude_mock.call_args_list[0][0][0]), [])

    @mock.patch('mkt.developers.cron._region_exclude')
    def test_called_with_future_exclusions(self, _region_exclude_mock):
        AddonExcludedRegion.objects.create(addon=self.app,
            region=mkt.regions.FUTURE.id)
        exclude_new_region([mkt.regions.CA])
        eq_(list(_region_exclude_mock.call_args_list[0][0][0]), [self.app.id])
