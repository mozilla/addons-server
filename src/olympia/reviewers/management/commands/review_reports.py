import os
from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils.encoding import force_str

import olympia.core.logger
from olympia import amo
from olympia.amo.utils import send_mail
from olympia.constants.reviewers import (
    POST_REVIEW_WEIGHT_HIGH_RISK,
    POST_REVIEW_WEIGHT_HIGHEST_RISK,
    POST_REVIEW_WEIGHT_MEDIUM_RISK,
)


SQL_DIR = os.path.join(
    settings.ROOT, 'src/olympia/reviewers/management/commands/review_reports_sql/'
)

REPORTS = {
    'addon': {
        'activities': (
            amo.LOG.APPROVE_VERSION,
            amo.LOG.REJECT_VERSION,
            amo.LOG.CONFIRM_AUTO_APPROVED,
            amo.LOG.REJECT_VERSION_DELAYED,
        ),
        'reports': (
            (
                'Weekly Add-on Reviews',
                os.path.join(SQL_DIR, 'addon/weekly.sql'),
            ),
            (
                'Weekly Add-on Reviews by Risk Profiles',
                os.path.join(SQL_DIR, 'addon/risk.sql'),
            ),
        ),
    },
    'content': {
        'activities': (
            amo.LOG.APPROVE_LISTING_CONTENT,
            amo.LOG.REJECT_LISTING_CONTENT,
            amo.LOG.REJECT_CONTENT,
            amo.LOG.REJECT_CONTENT_DELAYED,
        ),
        'reports': (
            (
                'Weekly Content Reviews',
                os.path.join(SQL_DIR, 'content/weekly.sql'),
            ),
        ),
    },
}

log = olympia.core.logger.getLogger('z.reviewers.review_report')


class Command(BaseCommand):
    help = 'Generate and send the review report'

    def handle(self, *args, **options):
        log.info('Generating add-on reviews report...')

        addon_report_data = self.fetch_report_data('addon')
        addon_report_html = self.generate_report_html('addon', addon_report_data)
        addon_report_subject = '{} {}-{}'.format(
            'Weekly Add-on Reviews Report',
            self.week_begin,
            self.week_end,
        )
        self.mail_report(
            'addon-reviewers@mozilla.org', addon_report_subject, addon_report_html
        )

        log.info('Generating content reviews report...')
        content_report_data = self.fetch_report_data('content')
        content_report_html = self.generate_report_html('content', content_report_data)
        content_report_subject = '{} {}-{}'.format(
            'Weekly Add-on Content Reviews Report',
            self.week_begin,
            self.week_end,
        )
        self.mail_report(
            'addon-content-reviewers@mozilla.com',
            content_report_subject,
            content_report_html,
        )

    def fetch_report_data(self, group):
        today = date.today()
        with connection.cursor() as cursor:
            # Set variables that are being used in the review report,
            # as well as the email output.
            cursor.execute(
                """
                SET @WEEK_BEGIN=%s;
                SET @WEEK_END=%s;
                SET @RISK_HIGHEST=%s;
                SET @RISK_HIGH=%s;
                SET @RISK_MEDIUM=%s;
                SET @ACTIVITY_ID_LIST=%s;
                """,
                [
                    today - timedelta(days=today.weekday() + 7),
                    today - timedelta(days=today.weekday() + 1),
                    POST_REVIEW_WEIGHT_HIGHEST_RISK,
                    POST_REVIEW_WEIGHT_HIGH_RISK,
                    POST_REVIEW_WEIGHT_MEDIUM_RISK,
                    ','.join(
                        str(activity.id) for activity in REPORTS[group]['activities']
                    ),
                ],
            )

            # Read the beginning/end of the week
            # in order to put it in the email.
            cursor.execute('SELECT @WEEK_BEGIN, @WEEK_END;')
            data = cursor.fetchone()
            self.week_begin = data[0]
            self.week_end = data[1]

            report_data = []

            for header, query_file in REPORTS[group]['reports']:
                with open(query_file) as report_query:
                    query_string = report_query.read().replace('\n', ' ')
                    cursor.execute(query_string)

                    table_header = []
                    for descr in cursor.description:
                        table_header.append(descr[0])
                    table_content = cursor.fetchall()
                    table_content = tuple(
                        tuple(force_str(item) for item in row) for row in table_content
                    )
                    report_data.append((header, table_header, table_content))

            return report_data

    def generate_report_html(self, group, report_data):
        # Pre-set email with style information and header
        all_html = """
            <h1 style="margin: 0; padding: 0;">Weekly Add-on {}Reviews Report</h1>
            <h3>{} - {}</h3>
            """.format(
            ('Content ' if group == 'content' else ''),
            self.week_begin,
            self.week_end,
        )
        h2 = '<h2 style="margin: 0; padding: 30px 0 10px 0;">'
        th = '<th style="text-align: left; padding: 0 12px;">'
        td_first = '<td style="padding: 0 12px; text-align: left; white-space: nowrap">'
        td_rest = '<td style="padding: 0 12px; text-align: right; white-space: nowrap">'

        # For each group, execute the individual SQL reports
        # and build the HTML email.

        for title, headers, rows in report_data:
            all_html += f'{h2}{title}</h2>\n'

            table_html = '<table>\n'
            table_html += f'<tr>{th}' + f'</th>{th}'.join(headers) + '</th></tr>\n'
            for row in rows:
                row_html = (
                    f'<tr>{td_first}' + f'</td>{td_rest}'.join(row) + '</td></tr>'
                )
                if row[0] == 'All Reviewers':
                    row_html = f'<tfoot style="text-weight: bold">{row_html}</tfoot>'
                table_html += row_html + '\n'
            table_html += '</table>\n'
            all_html += table_html

        return all_html

    def mail_report(self, recipient, subject, content):
        log.info(f"Sending report '{subject}' to {recipient}.")

        send_mail(
            subject,
            content,
            from_email='nobody@mozilla.org',
            recipient_list=[recipient],
            html_message=content,
            reply_to=[recipient],
        )
