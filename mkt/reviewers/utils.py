from datetime import datetime

from django.conf import settings
from django.template import Context, loader
from django.utils.datastructures import SortedDict

import commonware.log
import django_tables as tables
import jinja2
from tower import ugettext_lazy as _lazy

import amo
from amo.helpers import absolutify, timesince
from amo.urlresolvers import reverse
from amo.utils import send_mail as amo_send_mail
from editors.helpers import ItemStateTable

from mkt.webapps.models import Webapp


log = commonware.log.getLogger('z.mailer')


def send_mail(template, subject, emails, context, perm_setting=None):
    template = loader.get_template(template)
    # Link to our newfangled "Account Settings" page.
    manage_url = absolutify(reverse('account.settings')) + '#notifications'
    amo_send_mail(subject, template.render(Context(context, autoescape=False)),
                  recipient_list=emails,
                  from_email=settings.NOBODY_EMAIL,
                  use_blacklist=False, perm_setting=perm_setting,
                  manage_url=manage_url,
                  headers={'Reply-To': settings.MKT_REVIEWERS_EMAIL})


class WebappQueueTable(tables.ModelTable, ItemStateTable):
    name = tables.Column(verbose_name=_lazy(u'App'))
    created = tables.Column(verbose_name=_lazy(u'Waiting Time'))
    abuse_reports__count = tables.Column(verbose_name=_lazy(u'Abuse Reports'))

    def render_name(self, row):
        url = '%s?num=%s' % (self.review_url(row), self.item_number)
        self.increment_item()
        return u'<a href="%s">%s</a>' % (url, jinja2.escape(row.name))

    def render_abuse_reports__count(self, row):
        url = reverse('editors.abuse_reports', args=[row.slug])
        return u'<a href="%s">%s</a>' % (jinja2.escape(url),
                                         row.abuse_reports__count)

    def render_created(self, row):
        return timesince(row.created)

    @classmethod
    def translate_sort_cols(cls, colname):
        return colname

    @classmethod
    def default_order_by(cls):
        return 'created'

    @classmethod
    def review_url(cls, row):
        return reverse('reviewers.app_review', args=[row.app_slug])

    class Meta:
        sortable = True
        model = Webapp
        columns = ['name', 'created', 'abuse_reports__count']


class ReviewBase:

    def __init__(self, request, addon, version, review_type):
        self.request = request
        self.user = self.request.user
        self.addon = addon
        self.version = version
        self.review_type = review_type
        self.files = None

    def set_addon(self, **kw):
        """Alters addon and sets reviewed timestamp on version."""
        self.addon.update(**kw)
        self.version.update(reviewed=datetime.now())

    def set_files(self, status, files, copy_to_mirror=False,
                  hide_disabled_file=False):
        """Change the files to be the new status
        and copy, remove from the mirror as appropriate."""
        for file in files:
            file.datestatuschanged = datetime.now()
            file.reviewed = datetime.now()
            if copy_to_mirror:
                file.copy_to_mirror()
            if hide_disabled_file:
                file.hide_disabled_file()
            file.status = status
            file.save()

    def log_action(self, action):
        details = {'comments': self.data['comments'],
                   'reviewtype': self.review_type}
        if self.files:
            details['files'] = [f.id for f in self.files]

        amo.log(action, self.addon, self.version, user=self.user.get_profile(),
                created=datetime.now(), details=details)

    def notify_email(self, template, subject):
        """Notify the authors that their app has been reviewed."""
        emails = list(self.addon.authors.values_list('email', flat=True))
        data = self.data.copy()
        data.update(self.get_context_data())
        data['tested'] = ''
        os, app = data.get('operating_systems'), data.get('applications')
        if os and app:
            data['tested'] = 'Tested on %s with %s' % (os, app)
        elif os and not app:
            data['tested'] = 'Tested on %s' % os
        elif not os and app:
            data['tested'] = 'Tested with %s' % app
        send_mail('reviewers/emails/decisions/%s.txt' % template,
                  subject % self.addon.name,
                  emails, Context(data), perm_setting='app_reviewed')

    def get_context_data(self):
        return {'name': self.addon.name,
                'reviewer': self.request.user.get_profile().display_name,
                'detail_url': absolutify(
                    self.addon.get_url_path(add_prefix=False)),
                'review_url': absolutify(reverse('reviewers.app_review',
                                                 args=[self.addon.app_slug],
                                                 add_prefix=False)),
                'status_url': absolutify(self.addon.get_dev_url('versions')),
                'comments': self.data['comments'],
                'MKT_SUPPORT_EMAIL': settings.MKT_SUPPORT_EMAIL,
                'SITE_URL': settings.SITE_URL}

    def request_information(self):
        """Send a request for information to the authors."""
        emails = [a.email for a in self.addon.authors.all()]
        self.log_action(amo.LOG.REQUEST_INFORMATION)
        self.version.update(has_info_request=True)
        log.info(u'Sending request for information for %s to %s' %
                 (self.addon, emails))
        send_mail('reviewers/emails/decisions/info.txt',
                   u'Submission Update: %s' % self.addon.name,
                   emails, Context(self.get_context_data()),
                   perm_setting='app_individual_contact')

    def send_super_mail(self):
        self.log_action(amo.LOG.REQUEST_SUPER_REVIEW)
        log.info(u'Super review requested for %s' % self.addon)
        send_mail('reviewers/emails/super_review.txt',
                   u'Super Review Requested: %s' % self.addon.name,
                   [settings.MKT_SENIOR_EDITORS_EMAIL],
                   Context(self.get_context_data()))


class ReviewApp(ReviewBase):

    def set_data(self, data):
        self.data = data
        self.files = self.version.files.all()

    def process_public(self):
        """Approve an app."""
        # Save files first, because set_addon checks to make sure there
        # is at least one public file or it won't make the addon public.
        self.set_files(amo.STATUS_PUBLIC, self.version.files.all(),
                       copy_to_mirror=True)
        self.set_addon(highest_status=amo.STATUS_PUBLIC,
                       status=amo.STATUS_PUBLIC)

        self.log_action(amo.LOG.APPROVE_VERSION)
        self.notify_email('%s_to_public' % self.review_type,
                          u'App Approved: %s')

        log.info(u'Making %s public' % self.addon)
        log.info(u'Sending email for %s' % self.addon)

    def process_sandbox(self):
        """Reject an app."""
        self.set_addon(status=amo.STATUS_NULL)
        self.set_files(amo.STATUS_DISABLED, self.version.files.all(),
                       hide_disabled_file=True)

        self.log_action(amo.LOG.REJECT_VERSION)
        self.notify_email('%s_to_sandbox' % self.review_type,
                          u'Submission Update: %s')

        log.info(u'Making %s disabled' % self.addon)
        log.info(u'Sending email for %s' % self.addon)

    def process_super_review(self):
        """Ask for super review for an app."""
        self.addon.update(admin_review=True)
        self.notify_email('author_super_review', u'Submission Update: %s')

        self.send_super_mail()

    def process_comment(self):
        self.version.update(has_editor_comment=True)
        self.log_action(amo.LOG.COMMENT_VERSION)


class ReviewHelper:
    """
    A class that builds enough to render the form back to the user and
    process off to the correct handler.
    """

    def __init__(self, request=None, addon=None, version=None):
        self.handler = None
        self.required = {}
        self.addon = addon
        self.all_files = version.files.all()
        self.get_review_type(request, addon, version)
        self.actions = self.get_actions()

    def set_data(self, data):
        self.handler.set_data(data)

    def get_review_type(self, request, addon, version):
        if self.addon.type == amo.ADDON_WEBAPP:
            self.review_type = 'apps'
            self.handler = ReviewApp(request, addon, version, 'pending')

    def get_actions(self):
        actions = SortedDict()
        actions['public'] = {'method': self.handler.process_public,
                             'minimal': False,
                             'label': _lazy('Push to public'),
                             'details': _lazy(
                                'This will approve the sandboxed app so it '
                                'appears on the public side.')}
        actions['reject'] = {'method': self.handler.process_sandbox,
                             'label': _lazy('Reject'),
                             'minimal': False,
                             'details': _lazy(
                                'This will reject the app and remove it '
                                'from the review queue.')}
        actions['comment'] = {'method': self.handler.process_comment,
                              'label': _lazy('Comment'),
                              'minimal': True,
                              'details': _lazy(
                                    'Make a comment on this app.  The '
                                    'author won\'t be able to see this.')}
        return actions

    def process(self):
        action = self.handler.data.get('action', '')
        if not action:
            raise NotImplementedError
        return self.actions[action]['method']()
