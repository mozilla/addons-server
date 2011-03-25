from datetime import datetime

from django.conf import settings
from django.template import Context, loader
from django.utils.datastructures import SortedDict
import django_tables as tables
import jinja2
from jingo import register
from tower import ugettext_lazy as _, ungettext as ngettext

import amo
from amo.helpers import page_title, absolutify
from amo.urlresolvers import reverse
from amo.utils import send_mail as amo_send_mail

import commonware.log
from editors.models import (ViewPendingQueue, ViewFullReviewQueue,
                            ViewPreliminaryQueue)
from editors.sql_table import SQLTable


@register.function
def file_review_status(addon, file):
    if addon.status in [amo.STATUS_UNREVIEWED]:
        return _('Pending Preliminary Review')
    elif addon.status in [amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED,
                          amo.STATUS_PUBLIC]:
        return _('Pending Full Review')
    return amo.STATUS_CHOICES[file.status]


@register.function
@jinja2.contextfunction
def editor_page_title(context, title=None, addon=None):
    """Wrapper for editor page titles.  Eerily similar to dev_page_title."""
    if addon:
        title = u'%s :: %s' % (title, addon.name)
    else:
        section = _('Editor Tools')
        title = u'%s :: %s' % (title, section) if title else section
    return page_title(context, title)


class EditorQueueTable(SQLTable):
    addon_name = tables.Column(verbose_name=_(u'Addon'))
    addon_type_id = tables.Column(verbose_name=_(u'Type'))
    waiting_time_min = tables.Column(verbose_name=_(u'Waiting Time'))
    flags = tables.Column(verbose_name=_(u'Flags'), sortable=False)
    applications = tables.Column(verbose_name=_(u'Applications'),
                                 sortable=False)
    additional_info = tables.Column(verbose_name=_(u'Additional Information'),
                                    sortable=False)

    def render_addon_name(self, row):
        url = '%s?num=%s' % (reverse('editors.review',
                                     args=[row.latest_version_id]),
                             self.item_number)
        self.item_number += 1
        return u'<a href="%s">%s %s</a>' % (
                    url, jinja2.escape(row.addon_name),
                    jinja2.escape(row.latest_version))

    def render_addon_type_id(self, row):
        return amo.ADDON_TYPE[row.addon_type_id]

    def render_additional_info(self, row):
        info = []
        if row.is_site_specific:
            info.append(_(u'Site Specific'))
        if (len(row.file_platform_ids) == 1
            and row.file_platform_ids != [amo.PLATFORM_ALL.id]):
            k = row.file_platform_ids[0]
            # L10n: first argument is the platform such as Linux, Mac OS X
            info.append(_(u'{0} only').format(amo.PLATFORMS[k].name))
        if row.external_software:
            info.append(_(u'Requires External Software'))
        if row.binary:
            info.append(_(u'Binary Components'))
        return u', '.join([jinja2.escape(i) for i in info])

    def render_applications(self, row):
        # TODO(Kumar) show supported version ranges on hover (if still needed)
        icon = u'<div class="app-icon ed-sprite-%s" title="%s"></div>'
        return u''.join([icon % (amo.APPS_ALL[i].short, amo.APPS_ALL[i].pretty)
                         for i in row.application_ids])

    def render_flags(self, row):
        if not row.admin_review:
            return ''
        return (u'<div class="app-icon ed-sprite-admin-review" title="%s">'
                u'</div>' % _('Admin Review'))

    def render_waiting_time_min(self, row):
        if row.waiting_time_min == 0:
            r = _('moments ago')
        elif row.waiting_time_hours == 0:
            # L10n: first argument is number of minutes
            r = ngettext(u'{0} minute', u'{0} minutes',
                         row.waiting_time_min).format(row.waiting_time_min)
        elif row.waiting_time_days == 0:
            # L10n: first argument is number of hours
            r = ngettext(u'{0} hour', u'{0} hours',
                         row.waiting_time_hours).format(row.waiting_time_hours)
        else:
            # L10n: first argument is number of days
            r = ngettext(u'{0} day', u'{0} days',
                         row.waiting_time_days).format(row.waiting_time_days)
        return jinja2.escape(r)

    def set_page(self, page):
        self.item_number = page.start_index()

    class Meta:
        sortable = True
        columns = ['addon_name', 'addon_type_id', 'waiting_time_min',
                   'flags', 'applications', 'additional_info']


class ViewPendingQueueTable(EditorQueueTable):

    class Meta(EditorQueueTable.Meta):
        model = ViewPendingQueue


class ViewFullReviewQueueTable(EditorQueueTable):

    class Meta(EditorQueueTable.Meta):
        model = ViewFullReviewQueue


class ViewPreliminaryQueueTable(EditorQueueTable):

    class Meta(EditorQueueTable.Meta):
        model = ViewPreliminaryQueue


log = commonware.log.getLogger('z.mailer')


LOG_STATUSES = (amo.LOG.APPROVE_VERSION.id, amo.LOG.PRELIMINARY_VERSION.id,
                amo.LOG.REJECT_VERSION.id, amo.LOG.ESCALATE_VERSION.id,
                amo.LOG.RETAIN_VERSION.id)
NOMINATED_STATUSES = (amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED)
PRELIMINARY_STATUSES = (amo.STATUS_UNREVIEWED, amo.STATUS_LITE)
PENDING_STATUSES = (amo.STATUS_BETA, amo.STATUS_DISABLED, amo.STATUS_LISTED,
                    amo.STATUS_NULL, amo.STATUS_PENDING, amo.STATUS_PUBLIC)


def send_mail(template, subject, emails, context):
    template = loader.get_template(template)
    amo_send_mail(subject, template.render(Context(context)),
                  recipient_list=emails, from_email=settings.EDITORS_EMAIL,
                  use_blacklist=False)


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
        self.handler.data = data

    def get_review_type(self, request, addon, version):
        if self.addon.status in NOMINATED_STATUSES:
            self.review_type = 'nominated'
            self.handler = ReviewAddon(request, addon, version, 'nominated')

        elif self.addon.status == amo.STATUS_UNREVIEWED:
            self.review_type = 'preliminary'
            self.handler = ReviewAddon(request, addon, version, 'preliminary')

        elif self.addon.status == amo.STATUS_LITE:
            self.review_type = 'preliminary'
            self.handler = ReviewFiles(request, addon, version, 'preliminary')
        else:
            self.review_type = 'pending'
            self.handler = ReviewFiles(request, addon, version, 'preliminary')

    def get_actions(self):
        labels, details = self._review_actions()

        actions = SortedDict()
        if (self.review_type != 'preliminary' and
            hasattr(self.handler, 'process_public')):
            actions['public'] = {'method': self.handler.process_public,
                                 'minimal': False,
                                 'label': _('Push to public')}

        actions['prelim'] = {'method': self.handler.process_preliminary,
                             'label': labels['prelim'],
                             'minimal': False}
        actions['reject'] = {'method': self.handler.process_sandbox,
                             'label': _('Reject'),
                             'minimal': False}
        actions['info'] = {'method': self.handler.request_information,
                           'label': _('Request more information'),
                           'minimal': True}
        actions['super'] = {'method': self.handler.process_super_review,
                            'label': _('Request super-review'),
                            'minimal': True}
        for k, v in actions.items():
            v['details'] = details.get(k)

        return actions

    def _review_actions(self):
        labels = {'prelim': _('Grant preliminary review')}
        details = {'prelim': _('This will mark the files as '
                               'premliminary reviewed.'),
                   'info': _('Use this form to request more information from '
                             'the author. They will receive an email and be '
                             'able to answer here. You will be notified by '
                             'email when they reply.'),
                   'super': _('If you have concerns about this add-on\'s '
                              'security, copyright issues, or other concerns '
                              'that an administrator should look into, enter '
                              'your comments in the area below. They will be '
                              'sent to administrators, not the author.'),
                   'reject': _('This will reject the add-on and remove '
                               'it from the review queue.')}

        if self.addon.status == amo.STATUS_LITE:
            details['reject'] = _('This will reject the files and remove '
                                  'them from the review queue.')

        if self.addon.status in (amo.STATUS_UNREVIEWED, amo.STATUS_NOMINATED):
            details['prelim'] = _('This will mark the add-on as preliminarily '
                                  'reviewed. Future versions will undergo '
                                  'preliminary review.')
        elif self.addon.status == amo.STATUS_LITE:
            details['prelim'] = _('This will mark the files as preliminarily '
                                  'reviewed. Future versions will undergo '
                                  'preliminary review.')
        elif self.addon.status == amo.STATUS_LITE_AND_NOMINATED:
            labels['prelim'] = _('Retain preliminary review')
            details['prelim'] = _('This will retain the add-on as '
                                  'preliminarily reviewed. Future versions '
                                  'will undergo preliminary review.')
        if self.review_type == 'pending':
            details['reject'] = _('This will reject a version of a public '
                                  'add-on and remove it from the queue.')
        else:
            details['public'] = _('This will mark the add-on and its most '
                                  'recent version and files as public. Future '
                                  'versions will go into the sandbox until '
                                  'they are reviewed by an editor.')

        return labels, details

    def process(self):
        action = self.handler.data.get('action', '')
        if not action:
            raise NotImplementedError
        return self.actions[action]['method']()


class ReviewBase:

    def __init__(self, request, addon, version, review_type):
        self.request = request
        self.user = self.request.user
        self.addon = addon
        self.version = version
        self.review_type = review_type

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

    def log_approval(self, action):
        amo.log(action, self.addon, self.version, user=self.user.get_profile(),
                created=datetime.now(),
                details={'comments': self.data['comments'],
                         'reviewtype': self.review_type})

    def notify_email(self, template, subject):
        """Notify the authors that their addon has been reviewed."""
        emails = [a.email for a in self.addon.authors.all()]
        data = self.data.copy()
        data.update(self.get_context_data())
        send_mail('editors/emails/%s.ltxt' % template,
                   subject % (self.addon.name, self.version.version),
                   emails, Context(data))

    def get_context_data(self):
        return {'name': self.addon.name,
                'number': self.version.version,
                'reviewer': (self.request.user.get_profile().display_name),
                'addon_url': absolutify(reverse('addons.detail',
                                                args=[self.addon.slug])),
                'comments': self.data['comments'],
                'SITE_URL': settings.SITE_URL}

    def request_information(self):
        """Send a request for information to the authors."""
        emails = [a.email for a in self.addon.authors.all()]
        log.info(u'Sending request for information for %s to %s' %
                 (self.addon, emails))
        send_mail('editors/emails/info.ltxt',
                   _('Mozilla Add-ons: %s %s') %
                   (self.addon.name, self.version.version),
                   emails, Context(self.get_context_data()))

    def send_super_mail(self):
        log.info(u'Super review requested for %s' % (self.addon))
        send_mail('editors/emails/super_review.ltxt',
                   _('Super review requested: %s') % (self.addon.name),
                   [settings.SENIOR_EDITORS_EMAIL],
                   Context(self.get_context_data()))


class ReviewAddon(ReviewBase):

    def process_public(self):
        """Set an addon to public."""
        if self.review_type == 'preliminary':
            raise AssertionError('Preliminary addons cannot be made public.')

        # Save files first, because set_addon checks to make sure there
        # is at least one public file or it won't make the addon public.
        self.set_files(amo.STATUS_PUBLIC, self.version.files.all(),
                       copy_to_mirror=True)
        self.set_addon(highest_status=amo.STATUS_PUBLIC,
                       status=amo.STATUS_PUBLIC)

        self.log_approval(amo.LOG.APPROVE_VERSION)
        self.notify_email('%s_to_public' % self.review_type,
                          _('Mozilla Add-ons: %s %s Fully Reviewed'))

        log.info(u'Making %s public' % (self.addon))
        log.info(u'Sending email for %s' % (self.addon))

    def process_sandbox(self):
        """Set an addon back to sandbox."""
        self.set_addon(status=amo.STATUS_NULL)
        self.set_files(amo.STATUS_DISABLED, self.version.files.all(),
                       hide_disabled_file=True)

        self.log_approval(amo.LOG.REJECT_VERSION)
        self.notify_email('%s_to_sandbox' % self.review_type,
                          # L10n: addon name, version string
                          _('Mozilla Add-ons: %s %s Reviewed'))

        log.info(u'Making %s disabled' % (self.addon))
        log.info(u'Sending email for %s' % (self.addon))

    def process_preliminary(self):
        """Set an addon to preliminary."""
        changes = {'status': amo.STATUS_LITE}
        if (self.addon.status in (amo.STATUS_PUBLIC,
                                  amo.STATUS_LITE_AND_NOMINATED)):
            changes['highest_status'] = amo.STATUS_LITE

        template = '%s_to_preliminary' % self.review_type
        if (self.review_type == 'preliminary' and
            self.addon.status == amo.STATUS_LITE_AND_NOMINATED):
            template = 'nominated_to_nominated'

        self.set_addon(**changes)
        self.set_files(amo.STATUS_LITE, self.version.files.all(),
                       copy_to_mirror=True)

        self.log_approval(amo.LOG.PRELIMINARY_VERSION)
        self.notify_email(template,
                          # L10n: addon name, version string
                          _('Mozilla Add-ons: %s %s Preliminary Reviewed'))

        log.info(u'Making %s preliminary' % (self.addon))
        log.info(u'Sending email for %s' % (self.addon))

    def process_super_review(self):
        """Give an addon super review."""
        self.addon.update(admin_review=True)
        self.send_super_mail()


class ReviewFiles(ReviewBase):

    def process_sandbox(self):
        """Set an addon to sandbox."""
        self.set_files(amo.STATUS_DISABLED, self.data['addon_files'],
                       hide_disabled_file=True)

        self.log_approval(amo.LOG.REJECT_VERSION)
        self.notify_email('%s_to_preliminary' % self.review_type,
                          _('Mozilla Add-ons: %s %s Reviewed'))

        log.info(u'Making %s files %s disabled' %
                 (self.addon,
                  ', '.join([f.filename for f in self.data['addon_files']])))
        log.info(u'Sending email for %s' % (self.addon))

    def process_preliminary(self):
        """Set an addon to preliminary."""
        self.set_files(amo.STATUS_LITE, self.data['addon_files'],
                       copy_to_mirror=True)

        self.log_approval(amo.LOG.PRELIMINARY_VERSION)
        self.notify_email('%s_to_preliminary' % self.review_type,
                          _('Mozilla Add-ons: %s %s Preliminary Reviewed'))

        log.info(u'Making %s files %s preliminary' %
                 (self.addon,
                  ', '.join([f.filename for f in self.data['addon_files']])))
        log.info(u'Sending email for %s' % (self.addon))

    def process_super_review(self):
        """Give an addon super review when preliminary."""
        self.addon.update(admin_review=True)

        if any(f.status for f in self.data['addon_files'] if f.status
               in (amo.STATUS_PENDING, amo.STATUS_UNREVIEWED)):
            self.log_approval(amo.LOG.ESCALATE_VERSION)

        self.send_super_mail()
