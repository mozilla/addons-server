from StringIO import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from nose.tools import eq_, ok_, raises
from mock import patch

import amo
import amo.tests
from market.models import AddonPremium, Price
from mkt.developers.management.commands import (
    check_paid_app_regions)
from mkt.regions import (ALL_REGION_IDS, REGIONS_CHOICES_ID_DICT,
                         PL, US, WORLDWIDE)
from mkt.site.fixtures import fixture
from mkt.webapps.models import AddonExcludedRegion as AER, Webapp


class TestRegionManagmentCommand(amo.tests.TestCase):
    fixtures = fixture('webapp_337141', 'prices')

    @raises(CommandError)
    def test_unknown_slug(self):
        check_paid_app_regions.Command().handle('whatever')

    @patch('mkt.developers.forms.ALL_PAID_REGION_IDS', new=[PL.id, US.id])
    @patch('sys.stdout', new_callable=StringIO)
    def test_app_has_bad_regions(self, mock_stdout):
        app = Webapp.objects.get(id=337141)
        app.update(premium_type=amo.ADDON_PREMIUM)
        price = Price.objects.get(id=1)
        AddonPremium.objects.create(addon=app, price=price)
        call_command('check_paid_app_regions', app.app_slug)
        # From the fixture poland is the only ok region
        # for the price.
        stdout_val = mock_stdout.getvalue()
        assert 'Poland *' not in stdout_val
        assert '* Inappropriate region' in stdout_val

        for region_id in ALL_REGION_IDS:
            region_id = int(region_id)
            if region_id in (PL.id, US.id):
                continue
            region_name = unicode(REGIONS_CHOICES_ID_DICT.get(
                                  region_id).name)
            ok_('%s *' % region_name in stdout_val,
                '%s not present' % region_name)

    @raises(CommandError)
    def test_premium_no_price(self):
        app = Webapp.objects.get(id=337141)
        app.update(premium_type=amo.ADDON_PREMIUM)
        check_paid_app_regions.Command().handle(app.app_slug)

    @patch('sys.stdout', new_callable=StringIO)
    def test_include_region_by_id(self, mock_stdout):
        app = Webapp.objects.get(id=337141)
        app.update(premium_type=amo.ADDON_PREMIUM)
        price = Price.objects.get(id=1)
        AddonPremium.objects.create(addon=app, price=price)
        AER.objects.create(addon=app, region=WORLDWIDE.id)
        eq_(len(AER.objects.all()), 1)
        call_command('check_paid_app_regions', app.app_slug,
                     include_region_id=WORLDWIDE.id)
        eq_(AER.objects.all().exists(), False)

    @patch('sys.stdout', new_callable=StringIO)
    def test_exclude_region_by_id(self, mock_stdout):
        app = Webapp.objects.get(id=337141)
        app.update(premium_type=amo.ADDON_PREMIUM)
        price = Price.objects.get(id=1)
        AddonPremium.objects.create(addon=app, price=price)
        eq_(len(AER.objects.all()), 0)
        call_command('check_paid_app_regions', app.app_slug,
                     exclude_region_id=WORLDWIDE.id)
        eq_(AER.objects.get(addon=app).region, WORLDWIDE.id)

    @patch('sys.stdout', new_callable=StringIO)
    @patch('mkt.developers.forms.ALL_PAID_REGION_IDS', new=[PL.id, US.id])
    def test_free_with_inapp(self, mock_stdout):
        app = Webapp.objects.get(id=337141)
        app.update(premium_type=amo.ADDON_FREE_INAPP)
        call_command('check_paid_app_regions', app.app_slug)
        # From the fixture poland is the only ok region
        # for the price.
        stdout_val = mock_stdout.getvalue()
        assert 'Poland *' not in stdout_val
        assert 'United States *' not in stdout_val
        assert '* Inappropriate region' in stdout_val

    @raises(CommandError)
    def test_free_app(self):
        app = Webapp.objects.get(id=337141)
        app.update(premium_type=amo.ADDON_FREE)
        eq_(app.premium_type, amo.ADDON_FREE)
        check_paid_app_regions.Command().handle(app.app_slug)
