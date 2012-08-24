import datetime

from django.conf import settings
from django.template import Context, loader
from django.utils.datastructures import SortedDict
import django_tables as tables
import jinja2
from jingo import register
from tower import ugettext as _, ugettext_lazy as _lazy, ungettext as ngettext
import waffle

import amo
from addons.helpers import new_context
from amo.helpers import absolutify, breadcrumbs, page_title, timesince
from amo.urlresolvers import reverse
from amo.utils import send_mail as amo_send_mail

import commonware.log
from editors.models import (ReviewerScore, ViewFastTrackQueue,
                            ViewFullReviewQueue, ViewPendingQueue,
                            ViewPreliminaryQueue)
from editors.sql_table import SQLTable
from mkt.webapps.models import Webapp


@register.function
def file_compare(file_obj, version):
    # Compare this file to the one in the version with same platform
    file_obj = version.files.filter(platform=file_obj.platform)
    # If not there, just compare to all.
    if not file_obj:
        file_obj = version.files.filter(platform=amo.PLATFORM_ALL.id)
    # At this point we've got no idea what Platform file to
    # compare with, so just chose the first.
    if not file_obj:
        file_obj = version.files.all()
    return file_obj[0]


@register.function
def file_review_status(addon, file):
    if file.status not in [amo.STATUS_DISABLED, amo.STATUS_PUBLIC]:
        if addon.status in [amo.STATUS_UNREVIEWED, amo.STATUS_LITE]:
            return _(u'Pending Preliminary Review')
        elif addon.status in [amo.STATUS_NOMINATED,
                              amo.STATUS_LITE_AND_NOMINATED,
                              amo.STATUS_PUBLIC]:
            return _(u'Pending Full Review')
    return amo.STATUS_CHOICES[file.status]


@register.function
@jinja2.contextfunction
def editor_page_title(context, title=None, addon=None):
    """Wrapper for editor page titles.  Eerily similar to dev_page_title."""
    if addon:
        title = u'%s :: %s' % (title, addon.name)
    else:
        section = _lazy('Editor Tools')
        title = u'%s :: %s' % (title, section) if title else section
    return page_title(context, title)


@register.function
@jinja2.contextfunction
def editors_breadcrumbs(context, queue=None, addon_queue=None, items=None):
    """
    Wrapper function for ``breadcrumbs``. Prepends 'Editor Tools'
    breadcrumbs.

    **items**
        list of [(url, label)] to be inserted after Add-on.
    **addon_queue**
        Addon object. This sets the queue by addon type or addon status.
    **queue**
        Explicit queue type to set.
    """
    crumbs = [(reverse('editors.home'), _('Editor Tools'))]

    if addon_queue:
        if addon_queue.type == amo.ADDON_WEBAPP:
            queue = 'apps'
        else:
            queue_id = addon_queue.status
            queue_ids = {amo.STATUS_UNREVIEWED: 'prelim',
                         amo.STATUS_NOMINATED: 'nominated',
                         amo.STATUS_PUBLIC: 'pending',
                         amo.STATUS_LITE: 'prelim',
                         amo.STATUS_LITE_AND_NOMINATED: 'nominated',
                         amo.STATUS_PENDING: 'pending'}

            queue = queue_ids.get(queue_id, 'queue')

    if queue:
        queues = {'queue': _("Queue"),
                  'pending': _("Pending Updates"),
                  'nominated': _("Full Reviews"),
                  'prelim': _("Preliminary Reviews"),
                  'moderated': _("Moderated Reviews"),
                  'fast_track': _("Fast Track"),
                  'apps': _("Apps")}

        if items and not queue == 'queue':
            url = reverse('editors.queue_%s' % queue)
        else:
            # The Addon is the end of the trail.
            url = None
        crumbs.append((url, queues[queue]))

    if items:
        crumbs.extend(items)
    return breadcrumbs(context, crumbs, add_default=False)


@register.function
@jinja2.contextfunction
def queue_tabnav(context):
    """Returns tuple of tab navigation for the queue pages.

    Each tuple contains three elements: (tab_code, page_url, tab_text)
    """
    from .views import queue_counts
    counts = queue_counts()
    tabnav = [('fast_track', 'queue_fast_track',
               (ngettext('Fast Track ({0})', 'Fast Track ({0})',
                         counts['fast_track'])
                .format(counts['fast_track']))),
              ('nominated', 'queue_nominated',
               (ngettext('Full Review ({0})', 'Full Reviews ({0})',
                         counts['nominated'])
                .format(counts['nominated']))),
              ('pending', 'queue_pending',
               (ngettext('Pending Update ({0})', 'Pending Updates ({0})',
                         counts['pending'])
                .format(counts['pending']))),
              ('prelim', 'queue_prelim',
               (ngettext('Preliminary Review ({0})',
                         'Preliminary Reviews ({0})',
                         counts['prelim'])
                .format(counts['prelim']))),
              ('moderated', 'queue_moderated',
               (ngettext('Moderated Review ({0})', 'Moderated Reviews ({0})',
                         counts['moderated'])
                .format(counts['moderated'])))]

    if waffle.flag_is_active(context['request'], 'accept-webapps'):
        tabnav.append(('apps', 'queue_apps',
                       (ngettext('Apps ({0})', 'Apps ({0})', counts['apps'])
                        .format(counts['apps']))))
    return tabnav


@register.inclusion_tag('editors/includes/reviewers_score_bar.html')
@jinja2.contextfunction
def reviewers_score_bar(context):
    user = context.get('amo_user')

    return new_context(dict(
        amo=amo,
        points=ReviewerScore.get_recent(user),
        total=ReviewerScore.get_total(user),
        **ReviewerScore.get_leaderboards(user)))


class ItemStateTable(object):

    def increment_item(self):
        self.item_number += 1

    def set_page(self, page):
        self.item_number = page.start_index()


class EditorQueueTable(SQLTable, ItemStateTable):
    addon_name = tables.Column(verbose_name=_lazy(u'Addon'))
    addon_type_id = tables.Column(verbose_name=_lazy(u'Type'))
    waiting_time_min = tables.Column(verbose_name=_lazy(u'Waiting Time'))
    flags = tables.Column(verbose_name=_lazy(u'Flags'), sortable=False)
    applications = tables.Column(verbose_name=_lazy(u'Applications'),
                                 sortable=False)
    platforms = tables.Column(verbose_name=_lazy(u'Platforms'),
                              sortable=False)
    additional_info = tables.Column(
            verbose_name=_lazy(u'Additional'), sortable=False)

    def render_addon_name(self, row):
        url = '%s?num=%s' % (reverse('editors.review',
                                     args=[row.addon_slug]),
                             self.item_number)
        self.increment_item()
        return u'<a href="%s">%s <em>%s</em></a>' % (
                    url, jinja2.escape(row.addon_name),
                    jinja2.escape(row.latest_version))

    def render_addon_type_id(self, row):
        return amo.ADDON_TYPE[row.addon_type_id]

    def render_additional_info(self, row):
        info = []
        if row.is_site_specific:
            info.append(_lazy(u'Site Specific'))
        if row.external_software:
            info.append(_lazy(u'Requires External Software'))
        if row.binary or row.binary_components:
            info.append(_lazy(u'Binary Components'))
        return u', '.join([jinja2.escape(i) for i in info])

    def render_applications(self, row):
        # TODO(Kumar) show supported version ranges on hover (if still needed)
        icon = u'<div class="app-icon ed-sprite-%s" title="%s"></div>'
        return u''.join([icon % (amo.APPS_ALL[i].short, amo.APPS_ALL[i].pretty)
                         for i in row.application_ids])

    def render_platforms(self, row):
        icons = []
        html = u'<div class="platform-icon plat-sprite-%s" title="%s"></div>'
        for i in row.file_platform_vers:
            platform, version = i.split('-')
            if int(version) == row.latest_version_id:
                icons.append(html % (amo.PLATFORMS[int(platform)].shortname,
                                     amo.PLATFORMS[int(platform)].name))
        return u''.join(icons)

    def render_flags(self, row):
        o = []

        if row.admin_review:
            o.append(u'<div class="app-icon ed-sprite-admin-review" '
                     u'title="%s"></div>' % _('Admin Review'))

        if row.is_jetpack:
            o.append(u'<div class="app-icon ed-sprite-jetpack" title="%s">'
                     u'</div>' % _('Jetpack Add-on'))
        elif row.is_restartless:
            # Only show restartless if it's not also a jetpack
            o.append(u'<div class="app-icon ed-sprite-restartless" title="%s">'
                     u'</div>' % _('Bootstrapped Restartless Add-on'))

        if row.is_premium:
            o.append(u'<div class="app-icon ed-sprite-premium" title="%s">'
                     u'</div>' % _('Premium add-on'))

        if row.has_info_request:
            o.append(u'<div class="app-icon ed-sprite-info" title="%s">'
                     u'</div>' % _('More Information Requested'))

        if row.has_editor_comment:
            o.append(u'<div class="app-icon ed-sprite-editor" title="%s">'
                     u'</div>' % _('Contains Editor Comment'))

        return ''.join(o)

    def render_waiting_time_min(self, row):
        if row.waiting_time_min == 0:
            r = _lazy('moments ago')
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

    @classmethod
    def translate_sort_cols(cls, colname):
        legacy_sorts = {
            'name': 'addon_name',
            'age': 'waiting_time_min',
            'type': 'addon_type_id',
        }
        return legacy_sorts.get(colname, colname)

    @classmethod
    def default_order_by(cls):
        return '-waiting_time_min'

    @classmethod
    def review_url(cls, row):
        return reverse('editors.review', args=[row.addon_slug])

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


class ViewFastTrackQueueTable(EditorQueueTable):

    class Meta(EditorQueueTable.Meta):
        model = ViewFastTrackQueue


class WebappQueueTable(tables.ModelTable, ItemStateTable):
    name = tables.Column(verbose_name=_lazy(u'App'))
    created = tables.Column(verbose_name=_lazy(u'Waiting Time'))
    abuse_reports__count = tables.Column(verbose_name=_lazy(u'Abuse Reports'))

    def render_name(self, row):
        url = '%s?num=%s' % (reverse('editors.app_review', args=[row.slug]),
                             self.item_number)
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
        return reverse('editors.app_review', args=[row.slug])

    class Meta:
        sortable = True
        model = Webapp
        columns = ['name', 'created', 'abuse_reports__count']


log = commonware.log.getLogger('z.mailer')


NOMINATED_STATUSES = (amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED)
PRELIMINARY_STATUSES = (amo.STATUS_UNREVIEWED, amo.STATUS_LITE)
PENDING_STATUSES = (amo.STATUS_BETA, amo.STATUS_DISABLED, amo.STATUS_LISTED,
                    amo.STATUS_NULL, amo.STATUS_PENDING, amo.STATUS_PUBLIC)


def send_mail(template, subject, emails, context, perm_setting=None):
    template = loader.get_template(template)
    amo_send_mail(subject, template.render(Context(context, autoescape=False)),
                  recipient_list=emails, from_email=settings.EDITORS_EMAIL,
                  use_blacklist=False, perm_setting=perm_setting)


def get_position(addon):
    version = addon.latest_version

    if not version:
        return False

    q = version.current_queue
    if not q:
        return False

    mins_query = q.objects.filter(id=addon.id)
    if mins_query.count() > 0:
        mins = mins_query[0].waiting_time_min
        pos = q.objects.having('waiting_time_min >=', mins).count()
        total = q.objects.count()
        return dict(mins=mins, pos=pos, total=total)

    return False


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
            self.handler = ReviewAddon(request, addon, version, 'pending')
        elif self.addon.status in NOMINATED_STATUSES:
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
            self.handler = ReviewFiles(request, addon, version, 'pending')

    def get_actions(self):
        if self.addon.type == amo.ADDON_WEBAPP:
            return self.get_app_actions()
        labels, details = self._review_actions()

        actions = SortedDict()
        if self.review_type != 'preliminary':
            actions['public'] = {'method': self.handler.process_public,
                                 'minimal': False,
                                 'label': _lazy('Push to public')}

        if not self.addon.is_premium():
            actions['prelim'] = {'method': self.handler.process_preliminary,
                                 'label': labels['prelim'],
                                 'minimal': False}

        actions['reject'] = {'method': self.handler.process_sandbox,
                             'label': _lazy('Reject'),
                             'minimal': False}
        actions['info'] = {'method': self.handler.request_information,
                           'label': _lazy('Request more information'),
                           'minimal': True}
        actions['super'] = {'method': self.handler.process_super_review,
                            'label': _lazy('Request super-review'),
                            'minimal': True}
        actions['comment'] = {'method': self.handler.process_comment,
                              'label': _lazy('Comment'),
                              'minimal': True}
        for k, v in actions.items():
            v['details'] = details.get(k)

        return actions

    def get_app_actions(self):
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

    def _review_actions(self):
        labels = {'prelim': _lazy('Grant preliminary review')}
        details = {'prelim': _lazy('This will mark the files as '
                                   'premliminary reviewed.'),
                   'info': _lazy('Use this form to request more information '
                                 'from the author. They will receive an email '
                                 'and be able to answer here. You will be '
                                 'notified by email when they reply.'),
                   'super': _lazy('If you have concerns about this add-on\'s '
                                  'security, copyright issues, or other '
                                  'concerns that an administrator should look '
                                  'into, enter your comments in the area '
                                  'below. They will be sent to '
                                  'administrators, not the author.'),
                   'reject': _lazy('This will reject the add-on and remove '
                                   'it from the review queue.'),
                   'comment': _lazy('Make a comment on this version.  The '
                                    'author won\'t be able to see this.')}

        if self.addon.status == amo.STATUS_LITE:
            details['reject'] = _lazy('This will reject the files and remove '
                                      'them from the review queue.')

        if self.addon.status in (amo.STATUS_UNREVIEWED, amo.STATUS_NOMINATED):
            details['prelim'] = _lazy('This will mark the add-on as '
                                      'preliminarily reviewed. Future '
                                      'versions will undergo '
                                      'preliminary review.')
        elif self.addon.status == amo.STATUS_LITE:
            details['prelim'] = _lazy('This will mark the files as '
                                      'preliminarily reviewed. Future '
                                      'versions will undergo '
                                      'preliminary review.')
        elif self.addon.status == amo.STATUS_LITE_AND_NOMINATED:
            labels['prelim'] = _lazy('Retain preliminary review')
            details['prelim'] = _lazy('This will retain the add-on as '
                                      'preliminarily reviewed. Future '
                                      'versions will undergo preliminary '
                                      'review.')
        if self.review_type == 'pending':
            details['public'] = _lazy('This will approve a sandboxed version '
                                      'of a public add-on to appear on the '
                                      'public side.')
            details['reject'] = _lazy('This will reject a version of a public '
                                      'add-on and remove it from the queue.')
        else:
            details['public'] = _lazy('This will mark the add-on and its most '
                                      'recent version and files as public. '
                                      'Future versions will go into the '
                                      'sandbox until they are reviewed by an '
                                      'editor.')

        return labels, details

    def process(self):
        action = self.handler.data.get('action', '')
        if not action:
            raise NotImplementedError
        return self.actions[action]['method']()


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
        self.version.update(reviewed=datetime.datetime.now())

    def set_files(self, status, files, copy_to_mirror=False,
                  hide_disabled_file=False):
        """Change the files to be the new status
        and copy, remove from the mirror as appropriate."""
        for file in files:
            file.datestatuschanged = datetime.datetime.now()
            file.reviewed = datetime.datetime.now()
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
        if self.version:
            details['version'] = self.version.version

        amo.log(action, self.addon, self.version, user=self.user.get_profile(),
                created=datetime.datetime.now(), details=details)

    def notify_email(self, template, subject):
        """Notify the authors that their addon has been reviewed."""
        emails = [a.email for a in self.addon.authors.all()]
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
        data['addon_type'] = (_lazy('app')
                              if self.addon.type == amo.ADDON_WEBAPP
                              else _lazy('add-on'))
        send_mail('editors/emails/%s.ltxt' % template,
                   subject % (self.addon.name, self.version.version),
                   emails, Context(data), perm_setting='editor_reviewed')

    def get_context_data(self):
        return {'name': self.addon.name,
                'number': self.version.version,
                'reviewer': (self.request.user.get_profile().display_name),
                'addon_url': absolutify(
                    self.addon.get_url_path(add_prefix=False)),
                'review_url': absolutify(reverse('editors.review',
                                                 args=[self.addon.pk],
                                                 add_prefix=False)),
                'comments': self.data['comments'],
                'SITE_URL': settings.SITE_URL}

    def request_information(self):
        """Send a request for information to the authors."""
        emails = [a.email for a in self.addon.authors.all()]
        self.log_action(amo.LOG.REQUEST_INFORMATION)
        self.version.update(has_info_request=True)
        log.info(u'Sending request for information for %s to %s' %
                 (self.addon, emails))
        send_mail('editors/emails/info.ltxt',
                   u'Mozilla Add-ons: %s %s' %
                   (self.addon.name, self.version.version),
                   emails, Context(self.get_context_data()),
                   perm_setting='individual_contact')

    def send_super_mail(self):
        self.log_action(amo.LOG.REQUEST_SUPER_REVIEW)
        log.info(u'Super review requested for %s' % (self.addon))
        send_mail('editors/emails/super_review.ltxt',
                   u'Super review requested: %s' % (self.addon.name),
                   [settings.SENIOR_EDITORS_EMAIL],
                   Context(self.get_context_data()))

    def process_comment(self):
        self.version.update(has_editor_comment=True)
        self.log_action(amo.LOG.COMMENT_VERSION)


class ReviewAddon(ReviewBase):

    def __init__(self, *args, **kwargs):
        super(ReviewAddon, self).__init__(*args, **kwargs)

        self.is_upgrade = (self.addon.status is amo.STATUS_LITE_AND_NOMINATED
                           and self.review_type == 'nominated')

    def set_data(self, data):
        self.data = data
        self.files = self.version.files.all()

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

        self.log_action(amo.LOG.APPROVE_VERSION)
        self.notify_email('%s_to_public' % self.review_type,
                          u'Mozilla Add-ons: %s %s Fully Reviewed')

        log.info(u'Making %s public' % (self.addon))
        log.info(u'Sending email for %s' % (self.addon))

        # Assign reviewer incentive scores.
        event = ReviewerScore.get_event_by_type(self.addon, self.review_type)
        ReviewerScore.award_points(self.request.amo_user, self.addon, event)

    def process_sandbox(self):
        """Set an addon back to sandbox."""

        if (not self.is_upgrade or
            not self.addon.versions.exclude(id=self.version.id)
                          .filter(files__status__in=amo.REVIEWED_STATUSES)):
            self.set_addon(status=amo.STATUS_NULL)
        else:
            self.set_addon(status=amo.STATUS_LITE)

        self.set_files(amo.STATUS_DISABLED, self.version.files.all(),
                       hide_disabled_file=True)

        self.log_action(amo.LOG.REJECT_VERSION)
        self.notify_email('%s_to_sandbox' % self.review_type,
                          u'Mozilla Add-ons: %s %s Rejected')

        log.info(u'Making %s disabled' % (self.addon))
        log.info(u'Sending email for %s' % (self.addon))

    def process_preliminary(self):
        """Set an addon to preliminary."""
        if self.addon.is_premium():
            raise AssertionError('Premium add-ons cannot become preliminary.')

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

        self.log_action(amo.LOG.PRELIMINARY_VERSION)
        self.notify_email(template,
                          u'Mozilla Add-ons: %s %s Preliminary Reviewed')

        log.info(u'Making %s preliminary' % (self.addon))
        log.info(u'Sending email for %s' % (self.addon))

        # Assign reviewer incentive scores.
        event = ReviewerScore.get_event_by_type(self.addon, 'preliminary')
        ReviewerScore.award_points(self.request.amo_user, self.addon, event)

    def process_super_review(self):
        """Give an addon super review."""
        self.addon.update(admin_review=True)
        self.notify_email('author_super_review',
                          u'Mozilla Add-ons: %s %s flagged for Admin Review')
        self.send_super_mail()


class ReviewFiles(ReviewBase):

    def set_data(self, data):
        self.data = data
        self.files = data.get('addon_files', None)

    def process_public(self):
        """Set an addons files to public."""
        if self.review_type == 'preliminary':
            raise AssertionError('Preliminary addons cannot be made public.')

        self.set_files(amo.STATUS_PUBLIC, self.data['addon_files'],
                       copy_to_mirror=True)

        self.log_action(amo.LOG.APPROVE_VERSION)
        self.notify_email('%s_to_public' % self.review_type,
                          u'Mozilla Add-ons: %s %s Fully Reviewed')

        log.info(u'Making %s files %s public' %
                 (self.addon,
                  ', '.join([f.filename for f in self.data['addon_files']])))
        log.info(u'Sending email for %s' % (self.addon))

        # Assign reviewer incentive scores.
        event = ReviewerScore.get_event_by_type(self.addon, self.review_type)
        ReviewerScore.award_points(self.request.amo_user, self.addon, event)

    def process_sandbox(self):
        """Set an addons files to sandbox."""
        self.set_files(amo.STATUS_DISABLED, self.data['addon_files'],
                       hide_disabled_file=True)

        self.log_action(amo.LOG.REJECT_VERSION)
        self.notify_email('%s_to_sandbox' % self.review_type,
                          u'Mozilla Add-ons: %s %s Rejected')

        log.info(u'Making %s files %s disabled' %
                 (self.addon,
                  ', '.join([f.filename for f in self.data['addon_files']])))
        log.info(u'Sending email for %s' % (self.addon))

    def process_preliminary(self):
        """Set an addons files to preliminary."""
        if self.addon.is_premium():
            raise AssertionError('Premium add-ons cannot become preliminary.')

        self.set_files(amo.STATUS_LITE, self.data['addon_files'],
                       copy_to_mirror=True)

        self.log_action(amo.LOG.PRELIMINARY_VERSION)
        self.notify_email('%s_to_preliminary' % self.review_type,
                          u'Mozilla Add-ons: %s %s Preliminary Reviewed')

        log.info(u'Making %s files %s preliminary' %
                 (self.addon,
                  ', '.join([f.filename for f in self.data['addon_files']])))
        log.info(u'Sending email for %s' % (self.addon))

        # Assign reviewer incentive scores.
        event = ReviewerScore.get_event_by_type(self.addon, self.review_type)
        ReviewerScore.award_points(self.request.amo_user, self.addon, event)

    def process_super_review(self):
        """Give an addon super review when preliminary."""
        self.addon.update(admin_review=True)

        if any(f.status for f in self.data['addon_files'] if f.status
               in (amo.STATUS_PENDING, amo.STATUS_UNREVIEWED)):
            self.log_action(amo.LOG.ESCALATE_VERSION)

        self.notify_email('author_super_review',
                          u'Mozilla Add-ons: %s %s flagged for Admin Review')

        self.send_super_mail()
