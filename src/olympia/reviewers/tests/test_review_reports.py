from datetime import date, timedelta
from freezegun import freeze_time

from django.core import mail

from olympia import amo
from olympia.amo.tests import TestCase, user_factory, addon_factory
from olympia.reviewers.management.commands.review_reports import Command
from olympia.reviewers.models import AutoApprovalSummary, ReviewerScore


class TestReviewReports(TestCase):
    today = date.today()
    last_week_begin = today - timedelta(days=today.weekday() + 7)
    last_week_end = today - timedelta(days=today.weekday() + 1)
    this_quarter_begin = date(today.year, (today.month - 1) // 3 * 3 + 1, 1)

    def create_and_review_addon(self, user, weight, verdict, content_review):
        addon = addon_factory()
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=verdict, weight=weight)
        ReviewerScore.award_points(
            user, addon, addon.status, version=addon.versions.all()[0],
            post_review=True, content_review=content_review)

    def generate_review_data(self):
        super(TestReviewReports, self).setUp()
        with freeze_time(self.last_week_begin):
            reviewer1 = user_factory(display_name='Volunteer A')
            reviewer2 = user_factory(display_name='Staff B')
            reviewer3 = user_factory(display_name='Volunteer Content C')
            reviewer4 = user_factory(display_name='Staff Content D')
            self.grant_permission(reviewer2, '', name='Staff')
            self.grant_permission(reviewer4, '', name='No Reviewer Incentives')

            data = [
                (reviewer1, 178, amo.AUTO_APPROVED, False),
                (reviewer1, 95, amo.AUTO_APPROVED, False),
                (reviewer1, 123, amo.NOT_AUTO_APPROVED, False),
                (reviewer1, 328, amo.AUTO_APPROVED, False),
                (reviewer1, 450, amo.AUTO_APPROVED, False),
                (reviewer1, 999, amo.NOT_AUTO_APPROVED, False),
                (reviewer1, 131, amo.AUTO_APPROVED, False),
                (reviewer1, 74, amo.NOT_AUTO_APPROVED, False),
                (reviewer1, 15, amo.AUTO_APPROVED, False),

                (reviewer2, 951, amo.NOT_AUTO_APPROVED, False),
                (reviewer2, 8421, amo.AUTO_APPROVED, False),
                (reviewer2, 281, amo.AUTO_APPROVED, False),
                (reviewer2, 54, amo.NOT_AUTO_APPROVED, False),
                (reviewer2, 91, amo.NOT_AUTO_APPROVED, False),
                (reviewer2, 192, amo.AUTO_APPROVED, False),
                (reviewer2, 222, amo.NOT_AUTO_APPROVED, False),

                (reviewer3, 178, amo.AUTO_APPROVED, True),
                (reviewer3, 95, amo.AUTO_APPROVED, True),
                (reviewer3, 123, amo.NOT_AUTO_APPROVED, True),
                (reviewer3, 328, amo.AUTO_APPROVED, True),
                (reviewer3, 450, amo.AUTO_APPROVED, True),
                (reviewer3, 999, amo.NOT_AUTO_APPROVED, True),
                (reviewer3, 131, amo.AUTO_APPROVED, True),
                (reviewer3, 74, amo.NOT_AUTO_APPROVED, True),
                (reviewer3, 15, amo.AUTO_APPROVED, True),
                (reviewer3, 48, amo.AUTO_APPROVED, True),
                (reviewer3, 87, amo.NOT_AUTO_APPROVED, True),
                (reviewer3, 265, amo.AUTO_APPROVED, True),

                (reviewer4, 951, amo.NOT_AUTO_APPROVED, True),
                (reviewer4, 8421, amo.AUTO_APPROVED, True),
                (reviewer4, 281, amo.AUTO_APPROVED, True),
                (reviewer4, 54, amo.NOT_AUTO_APPROVED, True),
                (reviewer4, 91, amo.NOT_AUTO_APPROVED, True),
                (reviewer4, 192, amo.AUTO_APPROVED, True),
                (reviewer4, 222, amo.NOT_AUTO_APPROVED, True),
                (reviewer4, 192, amo.AUTO_APPROVED, True),
                (reviewer4, 444, amo.NOT_AUTO_APPROVED, True),
                (reviewer4, 749, amo.AUTO_APPROVED, True),
            ]
            for review_action in data:
                self.create_and_review_addon(review_action[0],
                                             review_action[1],
                                             review_action[2],
                                             review_action[3])

    def test_report_addon_reviewer(self):
        self.generate_review_data()
        command = Command()
        data = command.fetch_report_data('addon')
        assert data == [
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
             ((u'Volunteer A', u'810', u'9'),))
        ]

        html = command.generate_report_html('addon', data)

        assert 'Weekly Add-on Reviews Report' in html
        assert 'Volunteer A' in html
        assert 'Staff B' in html

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

        assert data == [
            ('Weekly Content Reviews, 10 Reviews or More',
             ['Name', 'Staff', 'Points', 'Add-ons Reviewed'],
             ((u'Volunteer Content C', u'', '120', u'12'),
              (u'Staff Content D', u'*', '-', u'10'))),
            ('Weekly Volunteer Contribution Ratio',
             ['Group', 'Add-ons Reviewed'],
             ((u'All Reviewers', u'22'), (u'Volunteers', u'12'))),
            ('Quarterly contributions',
             ['Name', 'Points', 'Add-ons Reviewed'],
             ((u'Volunteer Content C', u'120', u'12'),))
        ]

        html = command.generate_report_html('content', data)

        assert 'Weekly Add-on Content Reviews Report' in html
        assert 'Volunteer Content C' in html
        assert 'Staff Content D' in html

        to = 'addon-content-reviewers@mozilla.org'
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
        assert 'Volunteer Content C' not in html
        assert 'Staff Content D' not in html

        to = 'addon-content-reviewers@mozilla.org'
        subject = '%s %s-%s' % (
                  'Weekly Add-on Content Reviews Report',
                  self.last_week_begin, self.last_week_end)
        command.mail_report(to, subject, html)

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert to in email.to
        assert subject in email.subject
