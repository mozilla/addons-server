import datetime

from django.conf import settings
from django.template import Context, loader
from django.utils.datastructures import SortedDict
from django.utils.encoding import force_text
from django.utils import translation
from django.utils.translation import (
    ugettext as _, ugettext_lazy as _lazy, ungettext as ngettext)

import commonware.log
import django_tables2 as tables
import jinja2
import waffle
from jingo import register

from olympia import amo
from olympia.access import acl
from olympia.access.models import GroupUser
from olympia.addons.helpers import new_context
from olympia.addons.models import Addon
from olympia.amo.helpers import absolutify, breadcrumbs, page_title
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import send_mail as amo_send_mail, to_language
from olympia.constants.base import REVIEW_LIMITED_DELAY_HOURS
from olympia.editors.models import (
    ReviewerScore, ViewFullReviewQueue, ViewPendingQueue,
    ViewPreliminaryQueue, ViewUnlistedAllList, ViewUnlistedFullReviewQueue,
    ViewUnlistedPendingQueue, ViewUnlistedPreliminaryQueue)
from olympia.lib.crypto.packaged import sign_file
from olympia.users.models import UserProfile


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
    # If the file is pending review, check the add-on status
    if file.status == amo.STATUS_UNREVIEWED:
        if addon.status in [amo.STATUS_NOMINATED, amo.STATUS_PUBLIC]:
            return _(u'Pending Full Review')
        if addon.status in [amo.STATUS_UNREVIEWED, amo.STATUS_LITE]:
            return _(u'Pending Preliminary Review')
    # Special case: prelim upgrading to full approval,
    # file can already be preliminary reviewed or not
    if (file.status in [amo.STATUS_LITE, amo.STATUS_UNREVIEWED] and
            addon.status == amo.STATUS_LITE_AND_NOMINATED):
        if addon.latest_version.version_int == file.version.version_int:
            return _(u'Pending Full Review')
    if file.status in [amo.STATUS_DISABLED, amo.STATUS_REJECTED]:
        if file.reviewed is not None:
            return _(u'Rejected')
        # Can't assume that if the reviewed date is missing its
        # unreviewed.  Especially for versions.
        else:
            return _(u'Rejected or Unreviewed')
    return file.STATUS_CHOICES[file.status]


@register.function
def version_status(addon, version):
    if version.deleted:
        return _(u'Deleted')
    return ','.join(unicode(s) for s in version.status)


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
def editors_breadcrumbs(context, queue=None, addon_queue=None, items=None,
                        themes=False):
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

    if themes:
        crumbs.append((reverse('editors.themes.home'), _('Themes')))

    if addon_queue:
        queue_id = addon_queue.status
        queue_ids = {amo.STATUS_UNREVIEWED: 'prelim',
                     amo.STATUS_NOMINATED: 'nominated',
                     amo.STATUS_PUBLIC: 'pending',
                     amo.STATUS_LITE: 'prelim',
                     amo.STATUS_LITE_AND_NOMINATED: 'nominated',
                     amo.STATUS_PENDING: 'pending'}

        queue = queue_ids.get(queue_id, 'queue')

    listed = not context.get('unlisted')

    if queue:
        if listed:
            queues = {
                'queue': _('Queue'),
                'pending': _('Pending Updates'),
                'nominated': _('Full Reviews'),
                'prelim': _('Preliminary Reviews'),
                'moderated': _('Moderated Reviews'),

                'pending_themes': _('Pending Themes'),
                'flagged_themes': _('Flagged Themes'),
                'rereview_themes': _('Update Themes'),
            }
        else:
            queues = {
                'queue': _('Queue'),
                'pending': _('Unlisted Pending Updates'),
                'nominated': _('Unlisted Full Reviews'),
                'prelim': _('Unlisted Preliminary Reviews'),
                'all': _('All Unlisted Add-ons'),
            }

        if items and not queue == 'queue':
            if listed:
                url = reverse('editors.queue_{0}'.format(queue))
            else:
                url = reverse('editors.unlisted_queue_{0}'.format(queue))
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
    counts = context['queue_counts']
    unlisted_counts = context['unlisted_queue_counts']
    listed = not context.get('unlisted')

    if listed:
        tabnav = [('nominated', 'queue_nominated',
                   (ngettext('Full Review ({0})',
                             'Full Reviews ({0})',
                             counts['nominated'])
                    .format(counts['nominated']))),
                  ('pending', 'queue_pending',
                   (ngettext('Pending Update ({0})',
                             'Pending Updates ({0})',
                             counts['pending'])
                    .format(counts['pending']))),
                  ('prelim', 'queue_prelim',
                   (ngettext('Preliminary Review ({0})',
                             'Preliminary Reviews ({0})',
                             counts['prelim'])
                    .format(counts['prelim']))),
                  ('moderated', 'queue_moderated',
                   (ngettext('Moderated Review ({0})',
                             'Moderated Reviews ({0})',
                             counts['moderated'])
                    .format(counts['moderated'])))]
    else:
        tabnav = [('nominated', 'unlisted_queue_nominated',
                   (ngettext('Unlisted Full Review ({0})',
                             'Unlisted Full Reviews ({0})',
                             unlisted_counts['nominated'])
                    .format(unlisted_counts['nominated']))),
                  ('pending', 'unlisted_queue_pending',
                   (ngettext('Unlisted Pending Update ({0})',
                             'Unlisted Pending Updates ({0})',
                             unlisted_counts['pending'])
                    .format(unlisted_counts['pending']))),
                  ('prelim', 'unlisted_queue_prelim',
                   (ngettext('Unlisted Preliminary Review ({0})',
                             'Unlisted Preliminary Reviews ({0})',
                             unlisted_counts['prelim'])
                    .format(unlisted_counts['prelim']))),
                  ('all', 'unlisted_queue_all',
                   (ngettext('All Unlisted Add-ons ({0})',
                             'All Unlisted Add-ons ({0})',
                             unlisted_counts['all'])
                    .format(unlisted_counts['all'])))]

    return tabnav


@register.inclusion_tag('editors/includes/reviewers_score_bar.html')
@jinja2.contextfunction
def reviewers_score_bar(context, types=None, addon_type=None):
    user = context.get('user')

    return new_context(dict(
        request=context.get('request'),
        amo=amo, settings=settings,
        points=ReviewerScore.get_recent(user, addon_type=addon_type),
        total=ReviewerScore.get_total(user),
        **ReviewerScore.get_leaderboards(user, types=types,
                                         addon_type=addon_type)))


@register.inclusion_tag('editors/includes/files_view.html')
@jinja2.contextfunction
def all_distinct_files(context, version):
    """Only display a file once even if it's been uploaded
    for several platforms."""
    # hashes_to_file will group files per hash:
    # {<file.hash>: [<file>, 'Windows / Mac OS X']}
    hashes_to_file = {}
    for file_ in version.all_files:
        display_name = force_text(amo.PLATFORMS[file_.platform].name)
        if file_.hash in hashes_to_file:
            hashes_to_file[file_.hash][1] += ' / ' + display_name
        else:
            hashes_to_file[file_.hash] = [file_, display_name]
    return new_context(dict(
        # We don't need the hashes in the template.
        distinct_files=hashes_to_file.values(),
        amo=context.get('amo'),
        addon=context.get('addon'),
        show_diff=context.get('show_diff'),
        version=version))


class ItemStateTable(object):

    def increment_item(self):
        self.item_number += 1

    def set_page(self, page):
        self.item_number = page.start_index()


def safe_substitute(string, *args):
    return string % tuple(jinja2.escape(arg) for arg in args)


class EditorQueueTable(tables.Table, ItemStateTable):
    addon_name = tables.Column(verbose_name=_lazy(u'Add-on'))
    addon_type_id = tables.Column(verbose_name=_lazy(u'Type'))
    waiting_time_min = tables.Column(verbose_name=_lazy(u'Waiting Time'))
    flags = tables.Column(verbose_name=_lazy(u'Flags'), orderable=False)
    application_ids = tables.Column(verbose_name=_lazy(u'Applications'),
                                    orderable=False)
    platforms = tables.Column(verbose_name=_lazy(u'Platforms'),
                              orderable=False)
    additional_info = tables.Column(
        verbose_name=_lazy(u'Additional'), orderable=False)
    show_version_notes = True

    class Meta:
        orderable = True

    def render_addon_name(self, record):
        url = reverse('editors.review', args=[record.addon_slug])
        self.increment_item()
        return u'<a href="%s">%s <em>%s</em></a>' % (
            url, jinja2.escape(record.addon_name),
            jinja2.escape(record.latest_version))

    def render_addon_type_id(self, record):
        return amo.ADDON_TYPE[record.addon_type_id]

    def render_additional_info(self, record):
        info = []
        if record.is_site_specific:
            info.append(_lazy(u'Site Specific'))
        if record.external_software:
            info.append(_lazy(u'Requires External Software'))
        if record.binary or record.binary_components:
            info.append(_lazy(u'Binary Components'))
        return u', '.join([jinja2.escape(i) for i in info])

    def render_application_ids(self, record):
        # TODO(Kumar) show supported version ranges on hover (if still needed)
        icon = u'<div class="app-icon ed-sprite-%s" title="%s"></div>'
        return u''.join([icon % (amo.APPS_ALL[i].short, amo.APPS_ALL[i].pretty)
                         for i in record.application_ids])

    def render_platforms(self, record):
        icons = []
        html = u'<div class="platform-icon plat-sprite-%s" title="%s"></div>'
        for platform in record.platforms:
            icons.append(html % (amo.PLATFORMS[int(platform)].shortname,
                                 amo.PLATFORMS[int(platform)].name))
        return u''.join(icons)

    def render_flags(self, record):
        return ''.join(u'<div class="app-icon ed-sprite-%s" '
                       u'title="%s"></div>' % flag
                       for flag in record.flags)

    @classmethod
    def translate_sort_cols(cls, colname):
        legacy_sorts = {
            'name': 'addon_name',
            'age': 'waiting_time_min',
            'type': 'addon_type_id',
        }
        return legacy_sorts.get(colname, colname)

    def render_waiting_time_min(self, record):
        if record.waiting_time_min == 0:
            r = _lazy('moments ago')
        elif record.waiting_time_hours == 0:
            # L10n: first argument is number of minutes
            r = ngettext(
                u'{0} minute', u'{0} minutes',
                record.waiting_time_min).format(record.waiting_time_min)
        elif record.waiting_time_days == 0:
            # L10n: first argument is number of hours
            r = ngettext(
                u'{0} hour', u'{0} hours',
                record.waiting_time_hours).format(record.waiting_time_hours)
        else:
            # L10n: first argument is number of days
            r = ngettext(
                u'{0} day', u'{0} days',
                record.waiting_time_days).format(record.waiting_time_days)
        return jinja2.escape(r)

    @classmethod
    def default_order_by(cls):
        return '-waiting_time_min'


class EditorAllListTable(tables.Table, ItemStateTable):
    addon_name = tables.Column(verbose_name=_lazy(u'Add-on'))
    guid = tables.Column(verbose_name=_lazy(u'GUID'))
    authors = tables.Column(verbose_name=_lazy(u'Authors'),
                            orderable=False)
    review_date = tables.Column(verbose_name=_lazy(u'Last Review'))
    version_date = tables.Column(verbose_name=_lazy(u'Last Update'))
    show_version_notes = False

    class Meta:
        pass

    def render_addon_name(self, record):
        url = reverse('editors.review', args=[
            record.addon_slug if record.addon_slug is not None else record.id])
        self.increment_item()
        return safe_substitute(u'<a href="%s">%s <em>%s</em></a>',
                               url, record.addon_name, record.latest_version)

    def render_guid(self, record):
        return safe_substitute(u'%s', record.guid)

    def render_version_date(self, record):
        return safe_substitute(u'<span>%s</span>', record.version_date)

    def render_review_date(self, record):
        if record.review_version_num is None:
            return _('No Reviews')
        return safe_substitute(
            u'<span class="addon-review-text">'
            u'<a href="#"><em>%s</em> on %s</a></span>',
            record.review_version_num, record.review_date)

    def render_authors(self, record):
        authors = record.authors
        if not len(authors):
            return ''
        more = '\n'.join(
            safe_substitute(u'%s', uname) for (_, uname) in authors)
        author_links = ''.join(
            safe_substitute(u'<a href="%s">%s</a>',
                            UserProfile.create_user_url(id_, username=uname),
                            uname)
            for (id_, uname) in authors[0:3])
        return u'<span title="%s">%s%s</span>' % (
            more, author_links, '...' if len(authors) > 3 else '')

    @classmethod
    def default_order_by(cls):
        return '-version_date'


class ViewPendingQueueTable(EditorQueueTable):

    class Meta(EditorQueueTable.Meta):
        model = ViewPendingQueue


class ViewFullReviewQueueTable(EditorQueueTable):

    class Meta(EditorQueueTable.Meta):
        model = ViewFullReviewQueue


class ViewPreliminaryQueueTable(EditorQueueTable):

    class Meta(EditorQueueTable.Meta):
        model = ViewPreliminaryQueue


class ViewUnlistedPendingQueueTable(EditorQueueTable):

    class Meta(EditorQueueTable.Meta):
        model = ViewUnlistedPendingQueue


class ViewUnlistedFullReviewQueueTable(EditorQueueTable):

    class Meta(EditorQueueTable.Meta):
        model = ViewUnlistedFullReviewQueue


class ViewUnlistedPreliminaryQueueTable(EditorQueueTable):

    class Meta(EditorQueueTable.Meta):
        model = ViewUnlistedPreliminaryQueue


class ViewUnlistedAllListTable(EditorAllListTable):

    class Meta(EditorQueueTable.Meta):
        model = ViewUnlistedAllList


log = commonware.log.getLogger('z.mailer')


NOMINATED_STATUSES = (amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED)
PRELIMINARY_STATUSES = (amo.STATUS_UNREVIEWED, amo.STATUS_LITE)
PENDING_STATUSES = (amo.STATUS_BETA, amo.STATUS_DISABLED, amo.STATUS_NULL,
                    amo.STATUS_PENDING, amo.STATUS_PUBLIC)


def send_mail(template, subject, emails, context, perm_setting=None):
    template = loader.get_template(template)
    amo_send_mail(subject, template.render(Context(context, autoescape=False)),
                  recipient_list=emails, from_email=settings.EDITORS_EMAIL,
                  use_blacklist=False, perm_setting=perm_setting)


@register.function
def get_position(addon):
    if addon.is_persona() and addon.is_pending():
        qs = (Addon.objects.filter(status=amo.STATUS_PENDING,
                                   type=amo.ADDON_PERSONA)
              .no_transforms().order_by('created')
              .values_list('id', flat=True))
        id_ = addon.id
        position = 0
        for idx, addon_id in enumerate(qs, start=1):
            if addon_id == id_:
                position = idx
                break
        total = qs.count()
        return {'pos': position, 'total': total}
    else:
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
        self.version = version
        self.get_review_type(request, addon, version)
        self.actions = self.get_actions(request, addon)

    def set_data(self, data):
        self.handler.set_data(data)

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
            self.handler = ReviewFiles(request, addon, version, 'pending')

    def get_actions(self, request, addon):
        actions = SortedDict()
        if request is None:
            # If request is not set, it means we are just (ab)using the
            # ReviewHelper for its `handler` attribute and we don't care about
            # the actions.
            return actions
        labels, details = self._review_actions()
        reviewable_because_complete = addon.status not in (
            amo.STATUS_NULL, amo.STATUS_DELETED)
        reviewable_because_admin = (
            not addon.admin_review or
            acl.action_allowed(request, 'ReviewerAdminTools', 'View'))
        reviewable_because_submission_time = (
            not is_limited_reviewer(request) or
            (addon.latest_version is not None and
                addon.latest_version.nomination is not None and
                (datetime.datetime.now() - addon.latest_version.nomination >=
                    datetime.timedelta(hours=REVIEW_LIMITED_DELAY_HOURS))))
        reviewable_because_pending = addon.latest_version is not None and (
            len(addon.latest_version.is_unreviewed) > 0 or
            addon.status == amo.STATUS_LITE_AND_NOMINATED)
        if (reviewable_because_complete and
                reviewable_because_admin and
                reviewable_because_submission_time and
                reviewable_because_pending):
            if self.review_type != 'preliminary':
                if addon.is_listed:
                    label = _lazy('Push to public')
                else:
                    label = _lazy('Grant full review')
                actions['public'] = {'method': self.handler.process_public,
                                     'minimal': False,
                                     'label': label}
            # An unlisted sideload add-on, which requests a full review, cannot
            # be granted a preliminary review.
            prelim_allowed = not waffle.flag_is_active(
                request, 'no-prelim-review') and addon.is_listed
            if prelim_allowed or self.review_type == 'preliminary':
                actions['prelim'] = {
                    'method': self.handler.process_preliminary,
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

    def _review_actions(self):
        labels = {'prelim': _lazy('Grant preliminary review')}
        details = {'prelim': _lazy('This will mark the files as '
                                   'preliminarily reviewed.'),
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
                   'comment': _lazy('Make a comment on this version. The '
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
                                      'public site.')
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
        if request:
            self.user = self.request.user
        else:
            # Use the addons team go-to user "Mozilla" for the automatic
            # validations.
            self.user = UserProfile.objects.get(pk=settings.TASK_USER_ID)
        self.addon = addon
        self.version = version
        self.review_type = review_type
        self.files = self.version.unreviewed_files if self.version else []

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
            args = (self.addon, self.version)
        else:
            args = (self.addon,)

        kwargs = {'user': self.user, 'created': datetime.datetime.now(),
                  'details': details}
        amo.log(action, *args, **kwargs)

    def notify_email(self, template, subject):
        """Notify the authors that their addon has been reviewed."""
        emails = [a.email for a in self.addon.authors.all()]
        data = self.data.copy() if self.data else {}
        data.update(self.get_context_data())
        data['tested'] = ''
        os, app = data.get('operating_systems'), data.get('applications')
        if os and app:
            data['tested'] = 'Tested on %s with %s' % (os, app)
        elif os and not app:
            data['tested'] = 'Tested on %s' % os
        elif not os and app:
            data['tested'] = 'Tested with %s' % app
        subject = subject % (data['name'],
                             self.version.version if self.version else '')
        send_mail('editors/emails/%s.ltxt' % template, subject,
                  emails, Context(data), perm_setting='editor_reviewed')

    def get_context_data(self):
        addon_url = self.addon.get_url_path(add_prefix=False)
        dev_ver_url = self.addon.get_dev_url('versions')
        # We need to display the name in some language that is relevant to the
        # recipient(s) instead of using the reviewer's. addon.default_locale
        # should work.
        if self.addon.name.locale != self.addon.default_locale:
            lang = to_language(self.addon.default_locale)
            with translation.override(lang):
                addon = Addon.unfiltered.get(pk=self.addon.pk)
        else:
            addon = self.addon
        return {'name': addon.name,
                'number': self.version.version if self.version else '',
                'reviewer': self.user.display_name,
                'addon_url': absolutify(addon_url),
                'dev_versions_url': absolutify(dev_ver_url),
                'review_url': absolutify(reverse('editors.review',
                                                 args=[self.addon.pk],
                                                 add_prefix=False)),
                'comments': self.data.get('comments'),
                'SITE_URL': settings.SITE_URL}

    def request_information(self):
        """Send a request for information to the authors."""
        emails = [a.email for a in self.addon.authors.all()]
        self.log_action(amo.LOG.REQUEST_INFORMATION)
        if self.version:
            kw = {'has_info_request': True}
            if not self.addon.is_listed and not self.version.reviewed:
                kw['reviewed'] = datetime.datetime.now()
            self.version.update(**kw)
        log.info(u'Sending request for information for %s to %s' %
                 (self.addon, emails))
        data = self.get_context_data()
        subject = u'Mozilla Add-ons: %s %s' % (
            data['name'], self.version.version if self.version else '')
        send_mail('editors/emails/info.ltxt', subject,
                  emails, Context(data),
                  perm_setting='individual_contact')

    def send_super_mail(self):
        self.log_action(amo.LOG.REQUEST_SUPER_REVIEW)
        log.info(u'Super review requested for %s' % (self.addon))
        data = self.get_context_data()
        send_mail('editors/emails/super_review.ltxt',
                  u'Super review requested: %s' % (data['name']),
                  [settings.SENIOR_EDITORS_EMAIL],
                  Context(data))

    def process_comment(self):
        if self.version:
            kw = {'has_editor_comment': True}
            if self.data.get('clear_info_request'):
                kw['has_info_request'] = False
            if not self.addon.is_listed and not self.version.reviewed:
                kw['reviewed'] = datetime.datetime.now()
            self.version.update(**kw)
        self.log_action(amo.LOG.COMMENT_VERSION)


class ReviewAddon(ReviewBase):

    def __init__(self, *args, **kwargs):
        super(ReviewAddon, self).__init__(*args, **kwargs)

        self.is_upgrade = (
            self.addon.status == amo.STATUS_LITE_AND_NOMINATED and
            self.review_type == 'nominated')

    def set_data(self, data):
        self.data = data

    def process_public(self, auto_validation=False):
        """Set an addon to public."""
        if self.review_type == 'preliminary':
            raise AssertionError('Preliminary addons cannot be made public.')

        # Sign addon.
        for file_ in self.files:
            sign_file(file_, settings.SIGNING_SERVER)

        # Hold onto the status before we change it.
        status = self.addon.status

        # Save files first, because set_addon checks to make sure there
        # is at least one public file or it won't make the addon public.
        self.set_files(amo.STATUS_PUBLIC, self.files, copy_to_mirror=True)
        self.set_addon(status=amo.STATUS_PUBLIC)

        self.log_action(amo.LOG.APPROVE_VERSION)
        template = u'%s_to_public' % self.review_type
        subject = u'Mozilla Add-ons: %s %s Fully Reviewed'
        if not self.addon.is_listed:
            template = u'unlisted_to_reviewed'
            if auto_validation:
                template = u'unlisted_to_reviewed_auto'
            subject = u'Mozilla Add-ons: %s %s signed and ready to download'
        self.notify_email(template, subject)

        log.info(u'Making %s public' % (self.addon))
        log.info(u'Sending email for %s' % (self.addon))

        # Assign reviewer incentive scores.
        if self.request and not auto_validation:
            ReviewerScore.award_points(self.request.user, self.addon, status)

    def process_sandbox(self):
        """Set an addon back to sandbox."""

        # Hold onto the status before we change it.
        status = self.addon.status

        if (not self.is_upgrade or
            not self.addon.versions.exclude(id=self.version.id)
                          .filter(files__status__in=amo.REVIEWED_STATUSES)):
            self.set_addon(status=amo.STATUS_NULL)
        else:
            self.set_addon(status=amo.STATUS_LITE)

        self.set_files(amo.STATUS_DISABLED, self.files,
                       hide_disabled_file=True)

        self.log_action(amo.LOG.REJECT_VERSION)
        template = u'%s_to_sandbox' % self.review_type
        subject = u'Mozilla Add-ons: %s %s didn\'t pass review'
        if not self.addon.is_listed:
            template = u'unlisted_to_sandbox'
            subject = u'Mozilla Add-ons: %s %s didn\'t pass review'
        self.notify_email(template, subject)

        log.info(u'Making %s disabled' % (self.addon))
        log.info(u'Sending email for %s' % (self.addon))

        # Assign reviewer incentive scores.
        if self.request:
            ReviewerScore.award_points(self.request.user, self.addon, status)

    def process_preliminary(self, auto_validation=False):
        """Set an addon to preliminary."""
        # Sign addon.
        for file_ in self.files:
            sign_file(file_, settings.PRELIMINARY_SIGNING_SERVER)

        # Hold onto the status before we change it.
        status = self.addon.status

        changes = {'status': amo.STATUS_LITE}
        template = u'%s_to_preliminary' % self.review_type
        subject = u'Mozilla Add-ons: %s %s Preliminary Reviewed'
        if (self.review_type == 'preliminary' and
                self.addon.status == amo.STATUS_LITE_AND_NOMINATED):
            template = u'nominated_to_nominated'
        if not self.addon.is_listed:
            template = u'unlisted_to_reviewed'
            if auto_validation:
                template = u'unlisted_to_reviewed_auto'
            subject = u'Mozilla Add-ons: %s %s signed and ready to download'

        self.set_addon(**changes)
        self.set_files(amo.STATUS_LITE, self.files, copy_to_mirror=True)

        self.log_action(amo.LOG.PRELIMINARY_VERSION)
        self.notify_email(template, subject)

        log.info(u'Making %s preliminary' % (self.addon))
        log.info(u'Sending email for %s' % (self.addon))

        if self.request and not auto_validation:
            # Assign reviewer incentive scores.
            ReviewerScore.award_points(self.request.user, self.addon, status)

    def process_super_review(self):
        """Give an addon super review."""
        self.addon.update(admin_review=True)
        self.notify_email('author_super_review',
                          u'Mozilla Add-ons: %s %s flagged for Admin Review')
        self.send_super_mail()


class ReviewFiles(ReviewBase):

    def set_data(self, data):
        self.data = data
        if 'addon_files' in data:
            self.files = data['addon_files']

    def process_public(self, auto_validation=False):
        """Set an addons files to public."""
        if self.review_type == 'preliminary':
            raise AssertionError('Preliminary addons cannot be made public.')

        # Sign addon.
        for file_ in self.files:
            sign_file(file_, settings.SIGNING_SERVER)

        # Hold onto the status before we change it.
        status = self.addon.status

        self.set_files(amo.STATUS_PUBLIC, self.files, copy_to_mirror=True)

        self.log_action(amo.LOG.APPROVE_VERSION)
        template = u'%s_to_public' % self.review_type
        subject = u'Mozilla Add-ons: %s %s Fully Reviewed'
        if not self.addon.is_listed:
            template = u'unlisted_to_reviewed'
            if auto_validation:
                template = u'unlisted_to_reviewed_auto'
            subject = u'Mozilla Add-ons: %s %s signed and ready to download'
        self.notify_email(template, subject)

        log.info(u'Making %s files %s public' %
                 (self.addon, ', '.join([f.filename for f in self.files])))
        log.info(u'Sending email for %s' % (self.addon))

        # Assign reviewer incentive scores.
        if self.request and not auto_validation:
            ReviewerScore.award_points(self.request.user, self.addon, status)

    def process_sandbox(self):
        """Set an addons files to sandbox."""
        # Hold onto the status before we change it.
        status = self.addon.status

        self.set_files(amo.STATUS_DISABLED, self.files,
                       hide_disabled_file=True)

        self.log_action(amo.LOG.REJECT_VERSION)
        template = u'%s_to_sandbox' % self.review_type
        subject = u'Mozilla Add-ons: %s %s didn\'t pass review'
        if not self.addon.is_listed:
            template = u'unlisted_to_sandbox'
            subject = u'Mozilla Add-ons: %s %s didn\'t pass review'
        self.notify_email(template, subject)

        log.info(u'Making %s files %s disabled' %
                 (self.addon,
                  ', '.join([f.filename for f in self.files])))
        log.info(u'Sending email for %s' % (self.addon))

        # Assign reviewer incentive scores.
        if self.request:
            ReviewerScore.award_points(self.request.user, self.addon, status)

    def process_preliminary(self, auto_validation=False):
        """Set an addons files to preliminary."""
        # Sign addon.
        for file_ in self.files:
            sign_file(file_, settings.PRELIMINARY_SIGNING_SERVER)

        # Hold onto the status before we change it.
        status = self.addon.status

        self.set_files(amo.STATUS_LITE, self.files, copy_to_mirror=True)

        self.log_action(amo.LOG.PRELIMINARY_VERSION)
        template = u'%s_to_preliminary' % self.review_type
        subject = u'Mozilla Add-ons: %s %s Preliminary Reviewed'
        if not self.addon.is_listed:
            template = u'unlisted_to_reviewed'
            if auto_validation:
                template = u'unlisted_to_reviewed_auto'
            subject = u'Mozilla Add-ons: %s %s signed and ready to download'
        self.notify_email(template, subject)

        log.info(u'Making %s files %s preliminary' %
                 (self.addon, ', '.join([f.filename for f in self.files])))
        log.info(u'Sending email for %s' % (self.addon))

        if self.request and not auto_validation:
            # Assign reviewer incentive scores.
            ReviewerScore.award_points(self.request.user, self.addon, status)

    def process_super_review(self):
        """Give an addon super review when preliminary."""
        self.addon.update(admin_review=True)

        self.notify_email('author_super_review',
                          u'Mozilla Add-ons: %s %s flagged for Admin Review')

        self.send_super_mail()


@register.function
@jinja2.contextfunction
def logs_tabnav_themes(context):
    """
    Returns tuple of tab navigation for the log pages.

    Each tuple contains three elements: (named url, tab_code, tab_text)
    """
    rv = [
        ('editors.themes.logs', 'themes', _('Reviews'))
    ]
    if acl.action_allowed(context['request'], 'SeniorPersonasTools', 'View'):
        rv.append(('editors.themes.deleted', 'deleted', _('Deleted')))

    return rv


@register.function
@jinja2.contextfunction
def queue_tabnav_themes(context):
    """Similar to queue_tabnav, but for themes."""
    tabs = []
    if acl.action_allowed(context['request'], 'Personas', 'Review'):
        tabs.append((
            'editors.themes.list', 'pending_themes', _('Pending'),
        ))
    if acl.action_allowed(context['request'], 'SeniorPersonasTools', 'View'):
        tabs.append((
            'editors.themes.list_flagged', 'flagged_themes', _('Flagged'),
        ))
        tabs.append((
            'editors.themes.list_rereview', 'rereview_themes',
            _('Updates'),
        ))
    return tabs


@register.function
@jinja2.contextfunction
def queue_tabnav_themes_interactive(context):
    """Tabnav for the interactive shiny theme queues."""
    tabs = []
    if acl.action_allowed(context['request'], 'Personas', 'Review'):
        tabs.append((
            'editors.themes.queue_themes', 'pending', _('Pending'),
        ))
    if acl.action_allowed(context['request'], 'SeniorPersonasTools', 'View'):
        tabs.append((
            'editors.themes.queue_flagged', 'flagged', _('Flagged'),
        ))
        tabs.append((
            'editors.themes.queue_rereview', 'rereview', _('Updates'),
        ))
    return tabs


@register.function
@jinja2.contextfunction
def is_expired_lock(context, lock):
    return lock.expiry < datetime.datetime.now()


def is_limited_reviewer(request):
    if request:
        return GroupUser.objects.filter(group__name='Limited Reviewers',
                                        user=request.user).exists()
    else:
        # `request` could be None if coming from management command.
        return False
