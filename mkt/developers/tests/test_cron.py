# -*- coding: utf-8 -*-
import datetime
import mock
from nose.tools import eq_

import amo.tests
from devhub.models import ActivityLog

import mkt
import mkt.constants
from mkt.developers.cron import (_flag_rereview_adult, exclude_new_region,
                                 process_iarc_changes, send_new_region_emails)
from mkt.webapps.models import IARCInfo


class TestSendNewRegionEmails(amo.tests.WebappTestCase):

    @mock.patch('mkt.developers.cron._region_email')
    def test_called(self, _region_email_mock):
        self.app.update(enable_new_regions=True)
        send_new_region_emails([mkt.regions.UK])
        eq_(list(_region_email_mock.call_args_list[0][0][0]), [self.app.id])

    @mock.patch('mkt.developers.cron._region_email')
    def test_not_called_with_exclusions(self, _region_email_mock):
        self.app.addonexcludedregion.create(region=mkt.regions.UK.id)
        send_new_region_emails([mkt.regions.UK])
        eq_(list(_region_email_mock.call_args_list[0][0][0]), [])

    @mock.patch('mkt.developers.cron._region_email')
    def test_not_called_with_enable_new_regions_false(self,
                                                      _region_email_mock):
        """Check enable_new_regions is False by default."""
        eq_(self.app.enable_new_regions, False)
        send_new_region_emails([mkt.regions.UK])
        eq_(list(_region_email_mock.call_args_list[0][0][0]), [])


class TestExcludeNewRegion(amo.tests.WebappTestCase):

    @mock.patch('mkt.developers.cron._region_exclude')
    def test_not_called_enable_new_regions_true(self, _region_exclude_mock):
        self.app.update(enable_new_regions=True)
        exclude_new_region([mkt.regions.UK])
        eq_(list(_region_exclude_mock.call_args_list[0][0][0]), [])

    @mock.patch('mkt.developers.cron._region_exclude')
    def test_not_called_with_ordinary_exclusions(self, _region_exclude_mock):
        self.app.addonexcludedregion.create(region=mkt.regions.UK.id)
        exclude_new_region([mkt.regions.UK])
        eq_(list(_region_exclude_mock.call_args_list[0][0][0]), [])

    @mock.patch('mkt.developers.cron._region_exclude')
    def test_called_with_enable_new_regions_false(self, _region_exclude_mock):
        # Check enable_new_regions is False by default.
        eq_(self.app.enable_new_regions, False)
        exclude_new_region([mkt.regions.UK])
        eq_(list(_region_exclude_mock.call_args_list[0][0][0]), [self.app.id])


class TestIARCChangesCron(amo.tests.TestCase):

    @mock.patch('lib.iarc.utils.render_xml')
    def test_no_date(self, _render):
        process_iarc_changes()
        _render.assert_called_with('get_rating_changes.xml', {
            'date_from': datetime.date.today() - datetime.timedelta(days=1),
            'date_to': datetime.date.today(),
        })

    @mock.patch('lib.iarc.utils.render_xml')
    def test_with_date(self, _render):
        date = datetime.date(2001, 1, 11)
        process_iarc_changes(date.strftime('%Y-%m-%d'))
        _render.assert_called_with('get_rating_changes.xml', {
            'date_from': date - datetime.timedelta(days=1),
            'date_to': date,
        })

    def test_processing(self):
        """
        The mock client always returns the same data. Set up the app so it
        matches the submission ID and verify the data is saved as expected.
        """
        amo.set_user(amo.tests.user_factory())
        app = amo.tests.app_factory()
        IARCInfo.objects.create(addon=app, submission_id=52,
                                security_code='FZ32CU8')
        app.set_content_ratings({
            mkt.ratingsbodies.CLASSIND: mkt.ratingsbodies.CLASSIND_L,
            mkt.ratingsbodies.ESRB: mkt.ratingsbodies.ESRB_E
        })

        process_iarc_changes()
        app = app.reload()

        # Check ratings.
        # CLASSIND should get updated. ESRB should stay the same.
        cr = app.content_ratings.get(
            ratings_body=mkt.ratingsbodies.CLASSIND.id)
        eq_(cr.rating, mkt.ratingsbodies.CLASSIND_18.id)
        cr = app.content_ratings.get(ratings_body=mkt.ratingsbodies.ESRB.id)
        eq_(cr.rating, mkt.ratingsbodies.ESRB_E.id)

        assert ActivityLog.objects.filter(
            action=amo.LOG.CONTENT_RATING_CHANGED.id).count()

        # Check descriptors.
        self.assertSetEqual(
            app.rating_descriptors.to_keys(),
            ['has_classind_shocking', 'has_classind_sex_content',
             'has_classind_drugs', 'has_classind_lang', 'has_classind_nudity',
             'has_classind_violence_extreme'])

    def test_rereview_flag_adult(self):
        amo.set_user(amo.tests.user_factory())
        app = amo.tests.app_factory()

        app.set_content_ratings({
            mkt.ratingsbodies.ESRB: mkt.ratingsbodies.ESRB_E,
            mkt.ratingsbodies.CLASSIND: mkt.ratingsbodies.CLASSIND_18,
        })
        _flag_rereview_adult(app, mkt.ratingsbodies.ESRB,
                             mkt.ratingsbodies.ESRB_T)
        assert not app.rereviewqueue_set.count()
        assert not ActivityLog.objects.filter(
            action=amo.LOG.CONTENT_RATING_TO_ADULT.id).exists()

        # Adult should get flagged to rereview.
        _flag_rereview_adult(app, mkt.ratingsbodies.ESRB,
                             mkt.ratingsbodies.ESRB_A)
        eq_(app.rereviewqueue_set.count(), 1)
        eq_(ActivityLog.objects.filter(
            action=amo.LOG.CONTENT_RATING_TO_ADULT.id).count(), 1)

        # Test things same same if rating stays the same as adult.
        app.set_content_ratings({
            mkt.ratingsbodies.ESRB: mkt.ratingsbodies.ESRB_A,
        })
        _flag_rereview_adult(app, mkt.ratingsbodies.ESRB,
                             mkt.ratingsbodies.ESRB_A)
        eq_(app.rereviewqueue_set.count(), 1)
        eq_(ActivityLog.objects.filter(
            action=amo.LOG.CONTENT_RATING_TO_ADULT.id).count(), 1)
