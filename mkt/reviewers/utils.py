from datetime import datetime

from django.conf import settings
from django.utils.datastructures import SortedDict

import commonware.log
from tower import ugettext_lazy as _lazy

import amo
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import send_mail_jinja
from editors.models import ReviewerScore

from .models import EscalationQueue


log = commonware.log.getLogger('z.mailer')


def send_mail(subject, template, context, emails, perm_setting=None, cc=None):
    # Link to our newfangled "Account Settings" page.
    manage_url = absolutify(reverse('account.settings')) + '#notifications'
    send_mail_jinja(subject, template, context, recipient_list=emails,
                    from_email=settings.NOBODY_EMAIL, use_blacklist=False,
                    perm_setting=perm_setting, manage_url=manage_url,
                    headers={'Reply-To': settings.MKT_REVIEWERS_EMAIL}, cc=cc)


class ReviewBase(object):

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
        cc_email = self.addon.mozilla_contact or None
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
        send_mail(subject % self.addon.name,
                  'reviewers/emails/decisions/%s.txt' % template, data,
                  emails, perm_setting='app_reviewed', cc=cc_email)

    def get_context_data(self):
        return {'name': self.addon.name,
                'reviewer': self.request.user.get_profile().name,
                'detail_url': absolutify(
                    self.addon.get_url_path(add_prefix=False)),
                'review_url': absolutify(reverse('reviewers.apps.review',
                                                 args=[self.addon.app_slug],
                                                 add_prefix=False)),
                'status_url': absolutify(self.addon.get_dev_url('versions')),
                'comments': self.data['comments'],
                'MKT_SUPPORT_EMAIL': settings.MKT_SUPPORT_EMAIL,
                'SITE_URL': settings.SITE_URL}

    def request_information(self):
        """Send a request for information to the authors."""
        emails = list(self.addon.authors.values_list('email', flat=True))
        cc_email = self.addon.mozilla_contact or None
        self.log_action(amo.LOG.REQUEST_INFORMATION)
        self.version.update(has_info_request=True)
        log.info(u'Sending request for information for %s to %s' %
                 (self.addon, emails))
        send_mail(u'Submission Update: %s' % self.addon.name,
                  'reviewers/emails/decisions/info.txt',
                  self.get_context_data(), emails,
                  perm_setting='app_individual_contact', cc=cc_email)

    def send_super_mail(self):
        self.log_action(amo.LOG.REQUEST_SUPER_REVIEW)
        log.info(u'Super review requested for %s' % self.addon)
        send_mail(u'Super Review Requested: %s' % self.addon.name,
                  'reviewers/emails/super_review.txt',
                  self.get_context_data(), [settings.MKT_SENIOR_EDITORS_EMAIL])


class ReviewApp(ReviewBase):

    def set_data(self, data):
        self.data = data
        self.files = self.version.files.all()

    def process_public(self):
        if self.addon.make_public == amo.PUBLIC_IMMEDIATELY:
            return self.process_public_immediately()
        return self.process_public_waiting()

    def process_public_waiting(self):
        """Make an app pending."""
        self.set_files(amo.STATUS_PUBLIC_WAITING, self.version.files.all())
        self.set_addon(highest_status=amo.STATUS_PUBLIC_WAITING,
                       status=amo.STATUS_PUBLIC_WAITING)

        self.log_action(amo.LOG.APPROVE_VERSION_WAITING)
        self.notify_email('%s_to_public_waiting' % self.review_type,
                          u'App Approved but waiting: %s')

        log.info(u'Making %s public but pending' % self.addon)
        log.info(u'Sending email for %s' % self.addon)

        # Assign reviewer incentive scores.
        event = ReviewerScore.get_event_by_type(self.addon)
        ReviewerScore.award_points(self.request.amo_user, self.addon, event)

    def process_public_immediately(self):
        """Approve an app."""
        # Save files first, because set_addon checks to make sure there
        # is at least one public file or it won't make the addon public.
        self.set_files(amo.STATUS_PUBLIC, self.version.files.all())
        self.set_addon(highest_status=amo.STATUS_PUBLIC,
                       status=amo.STATUS_PUBLIC)

        self.log_action(amo.LOG.APPROVE_VERSION)
        self.notify_email('%s_to_public' % self.review_type,
                          u'App Approved: %s')

        log.info(u'Making %s public' % self.addon)
        log.info(u'Sending email for %s' % self.addon)

        # Assign reviewer incentive scores.
        event = ReviewerScore.get_event_by_type(self.addon)
        ReviewerScore.award_points(self.request.amo_user, self.addon, event)

    def process_sandbox(self):
        """Reject an app."""
        self.set_addon(status=amo.STATUS_REJECTED)
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

    def process_clear_escalation(self):
        """Clear app from escalation queue."""
        EscalationQueue.objects.filter(addon=self.addon).delete()
        self.log_action(amo.LOG.ESCALATION_CLEARED)
        log.info(u'Escalation cleared for app: %s' % self.addon)

    def process_disable(self):
        """Disables app."""
        self.addon.update(status=amo.STATUS_DISABLED)
        EscalationQueue.objects.filter(addon=self.addon).delete()
        emails = list(self.addon.authors.values_list('email', flat=True))
        cc_email = self.addon.mozilla_contact or None
        send_mail(u'App disabled by reviewer: %s' % self.addon.name,
                  'reviewers/emails/decisions/disabled.txt',
                  self.get_context_data(), emails,
                  perm_setting='app_individual_contact', cc=cc_email)
        self.log_action(amo.LOG.APP_DISABLED)
        log.info(u'App %s has been disabled by a reviewer.' % self.addon)


class ReviewHelper(object):
    """
    A class that builds enough to render the form back to the user and
    process off to the correct handler.
    """

    def __init__(self, request=None, addon=None, version=None, queue=None):
        self.handler = None
        self.required = {}
        self.addon = addon
        self.all_files = version.files.all()
        self.get_review_type(request, addon, version, queue)
        self.actions = self.get_actions()

    def set_data(self, data):
        self.handler.set_data(data)

    def get_review_type(self, request, addon, version, queue):
        self.review_type = queue
        self.handler = ReviewApp(request, addon, version, queue)

    def get_actions(self):
        public = {
            'method': self.handler.process_public,
            'minimal': False,
            'label': _lazy('Push to public'),
            'details': _lazy('This will approve the sandboxed app so it '
                             'appears on the public side.')}
        reject = {
            'method': self.handler.process_sandbox,
            'label': _lazy('Reject'),
            'minimal': False,
            'details': _lazy('This will reject the app and remove it from the '
                             'review queue.')}
        info = {
            'method': self.handler.request_information,
            'label': _lazy('Request more information'),
            'minimal': True,
            'details': _lazy('This will send the author(s) an email '
                             'requesting more information.')}
        super = {
            'method': self.handler.process_super_review,
            'label': _lazy('Request super-review'),
            'minimal': True,
            'details': _lazy('Flag this app for an admin to review')}
        comment = {
            'method': self.handler.process_comment,
            'label': _lazy('Comment'),
            'minimal': True,
            'details': _lazy('Make a comment on this app.  The author won\'t '
                             'be able to see this.')}
        clear_escalation = {
            'method': self.handler.process_clear_escalation,
            'label': _lazy('Clear Escalation'),
            'minimal': True,
            'details': _lazy('Clear this app from the escalation queue. The '
                             'author will get no email or see comments here.')}
        disable = {
            'method': self.handler.process_disable,
            'label': _lazy('Disable app'),
            'minimal': True,
            'details': _lazy('Disable the app, removing it from public '
                             'results. Sends comments to author.')}

        actions = SortedDict()
        if self.review_type == 'pending':
            actions['public'] = public
            actions['reject'] = reject
            actions['info'] = info
            actions['super'] = super
            actions['comment'] = comment
        elif self.review_type == 'rereview':
            pass  # TODO(robhudson)
        elif self.review_type == 'escalated':
            actions['clear_escalation'] = clear_escalation
            actions['disable'] = disable
            actions['info'] = info
            actions['comment'] = comment

        return actions

    def process(self):
        action = self.handler.data.get('action', '')
        if not action:
            raise NotImplementedError
        return self.actions[action]['method']()
