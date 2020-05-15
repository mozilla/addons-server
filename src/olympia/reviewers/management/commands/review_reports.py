from datetime import date, timedelta

import os
import settings

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils.encoding import force_text

import olympia.core.logger

from olympia.amo.utils import send_mail
from olympia.constants.reviewers import (POST_REVIEW_WEIGHT_HIGHEST_RISK,
                                         POST_REVIEW_WEIGHT_HIGH_RISK,
                                         POST_REVIEW_WEIGHT_MEDIUM_RISK)

from premailer import transform

SQL_DIR = os.path.join(
    settings.ROOT,
    'src/olympia/reviewers/management/commands/review_reports_sql/')

REPORTS = {
    'addon': [('Weekly Add-on Reviews, 5 Reviews or More',
               os.path.join(SQL_DIR, 'addon/weekly.sql')),
              ('Weekly Volunteer Contribution Ratio',
               os.path.join(SQL_DIR, 'addon/breakdown.sql')),
              ('Weekly Add-on Reviews by Risk Profiles',
               os.path.join(SQL_DIR, 'addon/risk.sql')),
              ('Quarterly contributions',
               os.path.join(SQL_DIR, 'addon/quarterly.sql'))],
    'content': [('Weekly Content Reviews, 10 Reviews or More',
                 os.path.join(SQL_DIR, 'content/weekly.sql')),
                ('Weekly Volunteer Contribution Ratio',
                 os.path.join(SQL_DIR, 'content/breakdown.sql')),
                ('Quarterly contributions',
                 os.path.join(SQL_DIR, 'content/quarterly.sql'))]
}

log = olympia.core.logger.getLogger('z.reviewers.review_report')


class Command(BaseCommand):
    help = 'Generate and send the review report'

    def handle(self, *args, **options):
        log.info('Generating add-on reviews report...')

        addon_report_data = self.fetch_report_data('addon')
        addon_report_html = self.generate_report_html('addon',
                                                      addon_report_data)
        addon_report_subject = '%s %s-%s' % (
            'Weekly Add-on Reviews Report',
            self.week_begin, self.week_end)
        self.mail_report('addon-reviewers@mozilla.org',
                         addon_report_subject,
                         addon_report_html)

        log.info('Generating content reviews report...')
        content_report_data = self.fetch_report_data('content')
        content_report_html = self.generate_report_html('content',
                                                        content_report_data)
        content_report_subject = '%s %s-%s' % (
            'Weekly Add-on Content Reviews Report',
            self.week_begin, self.week_end)
        self.mail_report('addon-content-reviewers@mozilla.com',
                         content_report_subject,
                         content_report_html)

    def fetch_report_data(self, group):
        today = date.today()
        with connection.cursor() as cursor:
            # Set variables that are being used in the review report,
            # as well as the email output.
            cursor.execute("""
                SET @WEEK_BEGIN=%s;
                SET @WEEK_END=%s;
                SET @QUARTER_BEGIN=%s;
                SET @RISK_HIGHEST=%s;
                SET @RISK_HIGH=%s;
                SET @RISK_MEDIUM=%s;
                """, [today - timedelta(days=today.weekday() + 7),
                      today - timedelta(days=today.weekday() + 1),
                      date(today.year, (today.month - 1) // 3 * 3 + 1, 1),
                      POST_REVIEW_WEIGHT_HIGHEST_RISK,
                      POST_REVIEW_WEIGHT_HIGH_RISK,
                      POST_REVIEW_WEIGHT_MEDIUM_RISK])

            # Read the beginning/end of the week
            # in order to put it in the email.
            cursor.execute('SELECT @WEEK_BEGIN, @WEEK_END;')
            data = cursor.fetchone()
            self.week_begin = data[0]
            self.week_end = data[1]

            report_data = []

            for header, query_file in REPORTS.get(group):
                with open(query_file) as report_query:
                    query_string = report_query.read().replace('\n', ' ')
                    cursor.execute(query_string)

                    table_header = []
                    for descr in cursor.description:
                        table_header.append(descr[0])
                    table_content = cursor.fetchall()
                    table_content = tuple((
                        tuple((force_text(item) for item in row))
                        for row in table_content))
                    report_data.append((header, table_header, table_content))

            return report_data

    def generate_report_html(self, group, report_data):
        # Pre-set email with style information and header
        all_html = """
            <style>
            h1 { margin: 0; padding: 0; }
            h2 { margin: 0; padding: 30px 0 10px 0; }
            th { text-align: left; }
            th, td { padding: 0 12px; }
            td { text-align: right; white-space: nowrap; }
            td:first-child { text-align: left; white-space: nowrap; }
            </style>
            <h1>Weekly Add-on %sReviews Report</h1>
            <h3>%s - %s</h3>
            """ % (('Content ' if group == 'content' else ''),
                   self.week_begin, self.week_end)

        # For each group, execute the individual SQL reports
        # and build the HTML email.

        for section in report_data:
            all_html += '<h2>%s</h2>\n' % section[0]

            table_html = '<table>\n'
            table_html += '<tr><th>' + '</th><th>'.join(
                [header for header in section[1]]) + '</th></tr>\n'
            for row in section[2]:
                table_html += '<tr><td>' + '</td><td>'.join(
                    [entry for entry in row]) + '</td></tr>\n'
            table_html += '</table>\n'
            all_html += table_html

        # Some email clients (e.g. GMail) require all styles to be inline.
        # 'transform' takes the file-wide styles defined above and transforms
        # them to be inline styles.
        return transform(all_html)

    def mail_report(self, recipient, subject, content):
        log.info("Sending report '%s' to %s." % (subject, recipient))

        send_mail(subject,
                  content,
                  from_email='nobody@mozilla.org',
                  recipient_list=[recipient],
                  html_message=content,
                  reply_to=[recipient])
