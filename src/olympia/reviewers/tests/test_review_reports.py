from datetime import date, timedelta

from freezegun import freeze_time
import pytest

from django.core import mail

from olympia import amo
from olympia.amo.tests import addon_factory, grant_permission, user_factory
from olympia.reviewers.management.commands.review_reports import Command
from olympia.reviewers.models import AutoApprovalSummary, ReviewerScore


@pytest.mark.django_db
class TestReviewReports(object):

    # Dates are chosen on purpose:
    # 2019-01-07: part of the reported week is previous quarter (year even)
    # 2019-01-14: back to reported week being within the quarter
    @pytest.fixture(autouse=True, params=['2019-01-07', '2019-01-14'])
    def freeze_date(self, request):
        freezer = freeze_time(request.param)
        freezer.start()

        self.today = date.today()
        self.last_week_begin = self.today - timedelta(
            days=self.today.weekday() + 7)
        self.last_week_end = self.today - timedelta(
            days=self.today.weekday() + 1)
        self.this_quarter_begin = date(
            self.today.year, (self.today.month - 1) // 3 * 3 + 1, 1)

        yield
        freezer.stop()

    def create_and_review_addon(self, user, weight, verdict, content_review):
        addon = addon_factory()
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=verdict, weight=weight)
        ReviewerScore.award_points(
            user, addon, addon.status, version=addon.versions.all()[0],
            post_review=True, content_review=content_review)

    def generate_review_data(self):
        with freeze_time(self.last_week_begin):
            self.reviewer1 = user_factory(display_name='Volunteer A')
            self.reviewer2 = user_factory(display_name='Staff B')
            self.reviewer3 = user_factory(display_name=None)
            self.reviewer4 = user_factory(display_name='Staff Content D')
            self.reviewer5 = user_factory(display_name='Deleted')
            grant_permission(self.reviewer2, '', name='No Reviewer Incentives')
            grant_permission(self.reviewer4, '', name='No Reviewer Incentives')

            data = [
                (self.reviewer1, 178, amo.AUTO_APPROVED, False),
                (self.reviewer1, 95, amo.AUTO_APPROVED, False),
                (self.reviewer1, 123, amo.NOT_AUTO_APPROVED, False),
                (self.reviewer1, 328, amo.AUTO_APPROVED, False),
                (self.reviewer1, 450, amo.AUTO_APPROVED, False),
                (self.reviewer1, 999, amo.NOT_AUTO_APPROVED, False),
                (self.reviewer1, 131, amo.AUTO_APPROVED, False),
                (self.reviewer1, 74, amo.NOT_AUTO_APPROVED, False),
                (self.reviewer1, 15, amo.AUTO_APPROVED, False),

                (self.reviewer2, 951, amo.NOT_AUTO_APPROVED, False),
                (self.reviewer2, 8421, amo.AUTO_APPROVED, False),
                (self.reviewer2, 281, amo.AUTO_APPROVED, False),
                (self.reviewer2, 54, amo.NOT_AUTO_APPROVED, False),
                (self.reviewer2, 91, amo.NOT_AUTO_APPROVED, False),
                (self.reviewer2, 192, amo.AUTO_APPROVED, False),
                (self.reviewer2, 222, amo.NOT_AUTO_APPROVED, False),

                (self.reviewer3, 178, amo.AUTO_APPROVED, True),
                (self.reviewer3, 95, amo.AUTO_APPROVED, True),
                (self.reviewer3, 123, amo.NOT_AUTO_APPROVED, True),
                (self.reviewer3, 328, amo.AUTO_APPROVED, True),
                (self.reviewer3, 450, amo.AUTO_APPROVED, True),
                (self.reviewer3, 999, amo.NOT_AUTO_APPROVED, True),
                (self.reviewer3, 131, amo.AUTO_APPROVED, True),
                (self.reviewer3, 74, amo.NOT_AUTO_APPROVED, True),
                (self.reviewer3, 15, amo.AUTO_APPROVED, True),
                (self.reviewer3, 48, amo.AUTO_APPROVED, True),
                (self.reviewer3, 87, amo.NOT_AUTO_APPROVED, True),
                (self.reviewer3, 265, amo.AUTO_APPROVED, True),

                (self.reviewer4, 951, amo.NOT_AUTO_APPROVED, True),
                (self.reviewer4, 8421, amo.AUTO_APPROVED, True),
                (self.reviewer4, 281, amo.AUTO_APPROVED, True),
                (self.reviewer4, 54, amo.NOT_AUTO_APPROVED, True),
                (self.reviewer4, 91, amo.NOT_AUTO_APPROVED, True),
                (self.reviewer4, 192, amo.AUTO_APPROVED, True),
                (self.reviewer4, 222, amo.NOT_AUTO_APPROVED, True),
                (self.reviewer4, 192, amo.AUTO_APPROVED, True),
                (self.reviewer4, 444, amo.NOT_AUTO_APPROVED, True),
                (self.reviewer4, 749, amo.AUTO_APPROVED, True),

                (self.reviewer5, 523, amo.NOT_AUTO_APPROVED, True),
                (self.reviewer5, 126, amo.AUTO_APPROVED, True),
                (self.reviewer5, 246, amo.AUTO_APPROVED, False),
                (self.reviewer5, 8740, amo.NOT_AUTO_APPROVED, True),
                (self.reviewer5, 346, amo.NOT_AUTO_APPROVED, False),
                (self.reviewer5, 985, amo.AUTO_APPROVED, False),
                (self.reviewer5, 123, amo.NOT_AUTO_APPROVED, True),
                (self.reviewer5, 93, amo.AUTO_APPROVED, True),
                (self.reviewer5, 22, amo.NOT_AUTO_APPROVED, False),
                (self.reviewer5, 165, amo.AUTO_APPROVED, True),
            ]
            for review_action in data:
                self.create_and_review_addon(review_action[0],
                                             review_action[1],
                                             review_action[2],
                                             review_action[3])

            self.reviewer5.delete()
            mail.outbox = []

            # Search plugin (submitted before auto-approval was implemented)
            search_plugin = addon_factory(type=4)
            ReviewerScore.award_points(
                self.reviewer3, search_plugin, amo.STATUS_APPROVED,
                version=search_plugin.versions.all()[0], post_review=False,
                content_review=True)

            # Dictionary (submitted before auto-approval was implemented)
            dictionary = addon_factory(type=3)
            ReviewerScore.award_points(
                self.reviewer3, dictionary, amo.STATUS_APPROVED,
                version=dictionary.versions.all()[0], post_review=False,
                content_review=True)

    def test_report_addon_reviewer(self):
        self.generate_review_data()
        command = Command()
        data = command.fetch_report_data('addon')
        expected = [
            ('Weekly Add-on Reviews, 5 Reviews or More',
             ['Name', 'Staff', 'Total Risk', 'Average Risk', 'Points',
              'Add-ons Reviewed'],
             ((u'Staff B', u'*', u'10,212', u'1,458.86', '-', u'7'),
              (u'Volunteer A', u'', u'2,393', u'265.89', '810', u'9'))),
            ('Weekly Volunteer Contribution Ratio',
             ['Group', 'Total Risk', 'Average Risk', 'Add-ons Reviewed'],
             ((u'All Reviewers', u'12,605', u'787.81', u'16'),
              (u'Volunteers', u'2,393', u'265.89', u'9'))),
            ('Weekly Add-on Reviews by Risk Profiles',
             ['Risk Category', 'All Reviewers', 'Volunteers'],
             ((u'highest', u'6', u'3'), (u'high', u'3', u'1'),
              (u'medium', u'4', u'3'), (u'low', u'3', u'2'))),
            ('Quarterly contributions',
             ['Name', 'Points', 'Add-ons Reviewed'],
             # Empty here to cover edge-case, see below.
             ())
        ]
        # If 'last_week_begin', which is used to generate the review data
        # (see `generate_review_data`), doesn't fall into the previous quarter,
        # fill in quarterly contributions.
        if not self.last_week_begin < self.this_quarter_begin:
            expected[3] = ('Quarterly contributions',
                           ['Name', 'Points', 'Add-ons Reviewed'],
                           ((u'Volunteer A', u'810', u'9'),))
        assert data == expected

        html = command.generate_report_html('addon', data)

        assert 'Weekly Add-on Reviews Report' in html
        assert 'Volunteer A' in html
        assert 'Staff B' in html
        assert 'Deleted' not in html

        to = 'addon-reviewers@mozilla.org'
        subject = '%s %s-%s' % (
                  'Weekly Add-on Reviews Report',
                  self.last_week_begin, self.last_week_end)
        command.mail_report(to, subject, html)

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert to in email.to
        assert subject in email.subject

    def test_report_content_reviewer(self):
        self.generate_review_data()
        command = Command()
        data = command.fetch_report_data('content')

        expected = [
            ('Weekly Content Reviews, 10 Reviews or More',
             ['Name', 'Staff', 'Points', 'Add-ons Reviewed'],
             ((u'Firefox user {}'.format(self.reviewer3.id),
               u'', '140', u'14'),
              (u'Staff Content D', u'*', '-', u'10'))),
            ('Weekly Volunteer Contribution Ratio',
             ['Group', 'Add-ons Reviewed'],
             ((u'All Reviewers', u'24'), (u'Volunteers', u'14'))),
            ('Quarterly contributions',
             ['Name', 'Points', 'Add-ons Reviewed'],
             # Empty here to cover edge-case, see below.
             ())
        ]
        # If 'last_week_begin', which is used to generate the review data
        # (see `generate_review_data`), doesn't fall into the previous quarter,
        # fill in quarterly contributions.
        if not self.last_week_begin < self.this_quarter_begin:
            expected[2] = ('Quarterly contributions',
                           ['Name', 'Points', 'Add-ons Reviewed'],
                           ((u'Firefox user {}'.format(self.reviewer3.id),
                             u'140', u'14'),))
        assert data == expected

        html = command.generate_report_html('content', data)

        assert 'Weekly Add-on Content Reviews Report' in html
        assert 'Firefox user {}'.format(self.reviewer3.id) in html
        assert 'Staff Content D' in html
        assert 'Deleted' not in html

        to = 'addon-content-reviewers@mozilla.com'
        subject = '%s %s-%s' % (
                  'Weekly Add-on Content Reviews Report',
                  self.last_week_begin, self.last_week_end)
        command.mail_report(to, subject, html)

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert to in email.to
        assert subject in email.subject

    def test_empty_report_addon_reviewer(self):
        command = Command()
        data = command.fetch_report_data('addon')
        assert data == [
            ('Weekly Add-on Reviews, 5 Reviews or More',
             ['Name', 'Staff', 'Total Risk', 'Average Risk', 'Points',
              'Add-ons Reviewed'],
             ()),
            ('Weekly Volunteer Contribution Ratio',
             ['Group', 'Total Risk', 'Average Risk', 'Add-ons Reviewed'],
             ((u'All Reviewers', u'-', u'-', u'0'),
              (u'Volunteers', u'-', u'-', u'0'))),
            ('Weekly Add-on Reviews by Risk Profiles',
             ['Risk Category', 'All Reviewers', 'Volunteers'],
             ()),
            ('Quarterly contributions',
             ['Name', 'Points', 'Add-ons Reviewed'],
             ())
        ]

        html = command.generate_report_html('addon', data)

        assert 'Weekly Add-on Reviews Report' in html
        assert 'Volunteer A' not in html
        assert 'Staff B' not in html
        assert 'Deleted' not in html

        to = 'addon-reviewers@mozilla.org'
        subject = '%s %s-%s' % (
                  'Weekly Add-on Reviews Report',
                  self.last_week_begin, self.last_week_end)
        command.mail_report(to, subject, html)

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert to in email.to
        assert subject in email.subject

    def test_empty_report_content_reviewer(self):
        command = Command()
        data = command.fetch_report_data('content')

        assert data == [
            ('Weekly Content Reviews, 10 Reviews or More',
             ['Name', 'Staff', 'Points', 'Add-ons Reviewed'],
             ()),
            ('Weekly Volunteer Contribution Ratio',
             ['Group', 'Add-ons Reviewed'],
             ((u'All Reviewers', u'0'), (u'Volunteers', u'0'))),
            ('Quarterly contributions',
             ['Name', 'Points', 'Add-ons Reviewed'],
             ())
        ]

        html = command.generate_report_html('content', data)

        assert 'Weekly Add-on Content Reviews Report' in html
        assert 'Firefox user' not in html
        assert 'Staff Content D' not in html
        assert 'Deleted' not in html

        to = 'addon-content-reviewers@mozilla.org'
        subject = '%s %s-%s' % (
                  'Weekly Add-on Content Reviews Report',
                  self.last_week_begin, self.last_week_end)
        command.mail_report(to, subject, html)

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert to in email.to
        assert subject in email.subject
