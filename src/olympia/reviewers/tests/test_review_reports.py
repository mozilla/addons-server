from datetime import date, timedelta

from django.core import mail

import pytest
import time_machine

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.tests import (
    addon_factory,
    grant_permission,
    user_factory,
    version_factory,
)
from olympia.reviewers.management.commands.review_reports import Command
from olympia.reviewers.models import AutoApprovalSummary


@pytest.mark.django_db
class TestReviewReports:
    # Dates are chosen on purpose:
    # 2019-01-07: part of the reported week is previous quarter (year even)
    # 2019-01-14: back to reported week being within the quarter
    @pytest.fixture(autouse=True, params=['2019-01-07', '2019-01-14'])
    def travel_to_date(self, request):
        machine = time_machine.travel(request.param, tick=False)
        machine.start()

        self.today = date.today()
        self.last_week_begin = self.today - timedelta(days=self.today.weekday() + 7)
        self.last_week_end = self.today - timedelta(days=self.today.weekday() + 1)
        self.this_quarter_begin = date(
            self.today.year, (self.today.month - 1) // 3 * 3 + 1, 1
        )

        yield
        machine.stop()

    def create_and_review_addon(self, user, weight, verdict, content_review):
        addon = addon_factory()
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=verdict, weight=weight
        )
        action = (
            amo.LOG.APPROVE_VERSION if not content_review else amo.LOG.APPROVE_CONTENT
        )
        ActivityLog.objects.create(action, addon, addon.versions.all()[0], user=user)

    def generate_review_data(self):
        with time_machine.travel(self.last_week_begin) as frozen_time:
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
                frozen_time.shift(1)
                self.create_and_review_addon(
                    review_action[0],
                    review_action[1],
                    review_action[2],
                    review_action[3],
                )

            self.reviewer5.delete()
            mail.outbox = []

            # Search plugin (submitted before auto-approval was implemented)
            search_plugin = addon_factory(type=4)
            frozen_time.shift(1)
            ActivityLog.objects.create(
                amo.LOG.APPROVE_CONTENT,
                search_plugin,
                search_plugin.versions.all()[0],
                user=self.reviewer3,
            )

            # Dictionary (submitted before auto-approval was implemented)
            dictionary = addon_factory(type=amo.ADDON_DICT)
            frozen_time.shift(1)
            ActivityLog.objects.create(
                amo.LOG.APPROVE_CONTENT,
                dictionary,
                dictionary.versions.all()[0],
                user=self.reviewer3,
            )

            # Theme (should be filtered out of the reports)
            theme = addon_factory(type=amo.ADDON_STATICTHEME)
            frozen_time.shift(1)
            ActivityLog.objects.create(
                amo.LOG.APPROVE_VERSION,
                theme,
                theme.versions.all()[0],
                user=self.reviewer2,
            )
            ActivityLog.objects.create(
                amo.LOG.APPROVE_CONTENT,
                theme,
                theme.versions.all()[0],
                user=self.reviewer1,
            )

    def test_report_addon_reviewer(self):
        self.generate_review_data()
        command = Command()
        data = command.fetch_report_data('addon')
        expected = [
            (
                'Weekly Add-on Reviews',
                [
                    'Name',
                    'Total Risk',
                    'Average Risk',
                    'Add-ons Reviewed',
                ],
                (
                    ('Staff B', '10,212', '1,458.86', '7'),
                    ('Volunteer A', '2,393', '265.89', '9'),
                    ('All Reviewers', '12,605', '787.81', '16'),
                ),
            ),
            (
                'Weekly Add-on Reviews by Risk Profiles',
                ['Risk Category', 'All Reviewers', 'Volunteers'],
                (
                    ('highest', '6', '3'),
                    ('high', '3', '1'),
                    ('medium', '4', '3'),
                    ('low', '3', '2'),
                ),
            ),
        ]
        assert data == expected

        html = command.generate_report_html('addon', data)

        assert 'Weekly Add-on Reviews Report' in html
        assert 'Volunteer A' in html
        assert 'Staff B' in html
        assert 'Deleted' not in html
        assert (
            '<tfoot style="text-weight: bold">'
            '<tr>'
            '<td style="padding: 0 12px; text-align: left; white-space: nowrap">'
            'All Reviewers'
            '</td>'
        ) in html

        to = 'addon-reviewers@mozilla.org'
        subject = '{} {}-{}'.format(
            'Weekly Add-on Reviews Report',
            self.last_week_begin,
            self.last_week_end,
        )
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
            (
                'Weekly Content Reviews',
                ['Name', 'Add-ons Reviewed'],
                (
                    (f'Firefox user {self.reviewer3.id}', '14'),
                    ('Staff Content D', '10'),
                    ('All Reviewers', '24'),
                ),
            ),
        ]
        assert data == expected

        html = command.generate_report_html('content', data)

        assert 'Weekly Add-on Content Reviews Report' in html
        assert f'Firefox user {self.reviewer3.id}' in html
        assert 'Staff Content D' in html
        assert 'Deleted' not in html

        to = 'addon-content-reviewers@mozilla.com'
        subject = '{} {}-{}'.format(
            'Weekly Add-on Content Reviews Report',
            self.last_week_begin,
            self.last_week_end,
        )
        command.mail_report(to, subject, html)

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert to in email.to
        assert subject in email.subject

    def test_empty_report_addon_reviewer(self):
        command = Command()
        data = command.fetch_report_data('addon')
        assert data == [
            (
                'Weekly Add-on Reviews',
                [
                    'Name',
                    'Total Risk',
                    'Average Risk',
                    'Add-ons Reviewed',
                ],
                (('All Reviewers', '-', '-', '0'),),
            ),
            (
                'Weekly Add-on Reviews by Risk Profiles',
                ['Risk Category', 'All Reviewers', 'Volunteers'],
                (),
            ),
        ]

        html = command.generate_report_html('addon', data)

        assert 'Weekly Add-on Reviews Report' in html
        assert 'Volunteer A' not in html
        assert 'Staff B' not in html
        assert 'Deleted' not in html

        to = 'addon-reviewers@mozilla.org'
        subject = '{} {}-{}'.format(
            'Weekly Add-on Reviews Report',
            self.last_week_begin,
            self.last_week_end,
        )
        command.mail_report(to, subject, html)

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert to in email.to
        assert subject in email.subject

    def test_empty_report_content_reviewer(self):
        command = Command()
        data = command.fetch_report_data('content')

        assert data == [
            (
                'Weekly Content Reviews',
                ['Name', 'Add-ons Reviewed'],
                (('All Reviewers', '0'),),
            ),
        ]

        html = command.generate_report_html('content', data)

        assert 'Weekly Add-on Content Reviews Report' in html
        assert 'Firefox user' not in html
        assert 'Staff Content D' not in html
        assert 'Deleted' not in html

        to = 'addon-content-reviewers@mozilla.org'
        subject = '{} {}-{}'.format(
            'Weekly Add-on Content Reviews Report',
            self.last_week_begin,
            self.last_week_end,
        )
        command.mail_report(to, subject, html)

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert to in email.to
        assert subject in email.subject

    def test_multiple_version_review_counted_once_addon_reviewer(self):
        self.reviewer1 = user_factory(display_name='Volunteer A')

        with time_machine.travel(self.last_week_begin, tick=False) as frozen_time:
            ActivityLog.objects.create(
                amo.LOG.APPROVE_VERSION,
                (addon := addon_factory()),
                addon.versions.all()[0],
                user=self.reviewer1,
            )
            frozen_time.shift(1)
            ActivityLog.objects.create(
                amo.LOG.CONFIRM_AUTO_APPROVED,
                (addon := addon_factory()),
                addon.versions.all()[0],
                user=self.reviewer1,
            )
            frozen_time.shift(1)
            ActivityLog.objects.create(
                amo.LOG.APPROVE_VERSION,
                (addon := addon_factory()),
                addon.versions.all()[0],
                user=self.reviewer1,
            )
            frozen_time.shift(1)
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION_DELAYED,
                (addon := addon_factory()),
                addon.versions.all()[0],
                user=self.reviewer1,
            )

            addon = addon_factory()
            version_factory(addon=addon)
            version_factory(addon=addon)
            all_versions = list(addon.versions.all())
            frozen_time.shift(1)
            # As these are logged at the exact same time, only 1 should be counted
            for i in range(3):
                ActivityLog.objects.create(
                    amo.LOG.REJECT_VERSION, addon, all_versions[i], user=self.reviewer1
                )
            # This should be ignored because it's an auto-rejection
            frozen_time.shift(1)
            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION,
                (addon := addon_factory()),
                addon.versions.all()[0],
                details={'comments': 'Automatic rejection after grace period ended.'},
                user=self.reviewer1,
            )

        command = Command()
        data = command.fetch_report_data('addon')
        expected = [
            (
                'Weekly Add-on Reviews',
                [
                    'Name',
                    'Total Risk',
                    'Average Risk',
                    'Add-ons Reviewed',
                ],
                (('Volunteer A', '0', '0', '5'), ('All Reviewers', '-', '-', '5')),
            ),
            (
                'Weekly Add-on Reviews by Risk Profiles',
                ['Risk Category', 'All Reviewers', 'Volunteers'],
                (),
            ),
        ]
        assert data == expected

    def test_multiple_version_review_counted_once_content_reviewer(self):
        self.reviewer1 = user_factory(display_name='Volunteer A')

        with time_machine.travel(self.last_week_begin, tick=False) as frozen_time:
            for _i in range(3):
                frozen_time.shift(1)
                ActivityLog.objects.create(
                    amo.LOG.APPROVE_CONTENT,
                    (addon := addon_factory()),
                    addon.versions.all()[0],
                    user=self.reviewer1,
                )
                frozen_time.shift(1)
                ActivityLog.objects.create(
                    amo.LOG.REJECT_CONTENT,
                    (addon := addon_factory()),
                    addon.versions.all()[0],
                    user=self.reviewer1,
                )
                frozen_time.shift(1)
                ActivityLog.objects.create(
                    amo.LOG.REJECT_CONTENT_DELAYED,
                    (addon := addon_factory()),
                    addon.versions.all()[0],
                    user=self.reviewer1,
                )

            addon = addon_factory()
            version_factory(addon=addon)
            version_factory(addon=addon)
            all_versions = list(addon.versions.all())
            frozen_time.shift(1)
            # As these are logged at the exact same time, only 1 should be counted
            for i in range(3):
                ActivityLog.objects.create(
                    amo.LOG.REJECT_CONTENT, addon, all_versions[i], user=self.reviewer1
                )
            # This should be ignored because it's an auto-rejection
            frozen_time.shift(1)
            ActivityLog.objects.create(
                amo.LOG.REJECT_CONTENT,
                (addon := addon_factory()),
                addon.versions.all()[0],
                details={'comments': 'Automatic rejection after grace period ended.'},
                user=self.reviewer1,
            )

        command = Command()
        data = command.fetch_report_data('content')
        expected = [
            (
                'Weekly Content Reviews',
                [
                    'Name',
                    'Add-ons Reviewed',
                ],
                (
                    ('Volunteer A', '10'),
                    ('All Reviewers', '10'),
                ),
            ),
        ]
        assert data == expected
