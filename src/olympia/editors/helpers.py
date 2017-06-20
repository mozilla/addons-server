import datetime
from collections import OrderedDict

from django.conf import settings
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.template import Context, loader
from django.utils.encoding import force_text
from django.utils import translation
from django.utils.translation import ugettext, ugettext_lazy as _, ungettext

import django_tables2 as tables
import jinja2
from jingo import register

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.access.models import GroupUser
from olympia.activity.models import ActivityLog
from olympia.activity.utils import send_activity_mail, log_and_notify
from olympia.addons.helpers import new_context
from olympia.addons.models import Addon, AddonApprovalsCounter
from olympia.amo.helpers import absolutify, page_title
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import to_language
from olympia.constants.base import REVIEW_LIMITED_DELAY_HOURS
from olympia.editors.models import (
    get_flags, ReviewerScore, ViewFullReviewQueue, ViewPendingQueue,
    ViewUnlistedAllList)
from olympia.lib.crypto.packaged import sign_file
from olympia.tags.models import Tag
from olympia.users.models import UserProfile
from olympia.versions.models import Version


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
    if file.status == amo.STATUS_DISABLED:
        if file.reviewed is not None:
            return ugettext(u'Rejected')
        # Can't assume that if the reviewed date is missing its
        # unreviewed.  Especially for versions.
        else:
            return ugettext(u'Rejected or Unreviewed')
    return file.STATUS_CHOICES.get(
        file.status, ugettext('[status:%s]') % file.status)


@register.function
def version_status(addon, version):
    if version.deleted:
        return ugettext(u'Deleted')
    return ','.join(unicode(s) for s in version.status)


@register.function
@jinja2.contextfunction
def editor_page_title(context, title=None, addon=None):
    """Wrapper for editor page titles.  Eerily similar to dev_page_title."""
    if addon:
        title = u'%s :: %s' % (title, addon.name)
    else:
        section = _('Reviewer Tools')
        title = u'%s :: %s' % (title, section) if title else section
    return page_title(context, title)


@register.function
@jinja2.contextfunction
def queue_tabnav(context):
    """Returns tuple of tab navigation for the queue pages.

    Each tuple contains three elements: (tab_code, page_url, tab_text)
    """
    counts = context['queue_counts']
    request = context['request']
    listed = not context.get('unlisted')

    if listed:
        tabnav = [('nominated', 'queue_nominated',
                   (ungettext('New Add-on ({0})',
                              'New Add-ons ({0})',
                              counts['nominated'])
                    .format(counts['nominated']))),
                  ('pending', 'queue_pending',
                   (ungettext('Update ({0})',
                              'Updates ({0})',
                              counts['pending'])
                    .format(counts['pending']))),
                  ('moderated', 'queue_moderated',
                   (ungettext('Moderated Review ({0})',
                              'Moderated Reviews ({0})',
                              counts['moderated'])
                    .format(counts['moderated'])))]

        if acl.action_allowed(request, amo.permissions.ADDONS_POST_REVIEW):
            tabnav.append(
                ('auto_approved', 'queue_auto_approved',
                 (ungettext('Auto Approved Add-on ({0})',
                            'Auto Approved Add-ons ({0})',
                            counts['auto_approved'])
                  .format(counts['auto_approved']))),
            )
    else:
        tabnav = [
            ('all', 'unlisted_queue_all', ugettext('All Unlisted Add-ons'))
        ]

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
    addon_name = tables.Column(verbose_name=_(u'Add-on'))
    addon_type_id = tables.Column(verbose_name=_(u'Type'))
    waiting_time_min = tables.Column(verbose_name=_(u'Waiting Time'))
    flags = tables.Column(verbose_name=_(u'Flags'), orderable=False)

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

    def render_flags(self, record):
        if not hasattr(record, 'flags'):
            record.flags = get_flags(record)
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
            r = _('moments ago')
        elif record.waiting_time_hours == 0:
            # L10n: first argument is number of minutes
            r = ungettext(
                u'{0} minute', u'{0} minutes',
                record.waiting_time_min).format(record.waiting_time_min)
        elif record.waiting_time_days == 0:
            # L10n: first argument is number of hours
            r = ungettext(
                u'{0} hour', u'{0} hours',
                record.waiting_time_hours).format(record.waiting_time_hours)
        else:
            # L10n: first argument is number of days
            r = ungettext(
                u'{0} day', u'{0} days',
                record.waiting_time_days).format(record.waiting_time_days)
        return jinja2.escape(r)

    @classmethod
    def default_order_by(cls):
        return '-waiting_time_min'


class ViewUnlistedAllListTable(tables.Table, ItemStateTable):
    addon_name = tables.Column(verbose_name=_(u'Add-on'))
    guid = tables.Column(verbose_name=_(u'GUID'))
    authors = tables.Column(verbose_name=_(u'Authors'),
                            orderable=False)
    review_date = tables.Column(verbose_name=_(u'Last Review'))
    version_date = tables.Column(verbose_name=_(u'Last Update'))

    class Meta(EditorQueueTable.Meta):
        model = ViewUnlistedAllList

    def render_addon_name(self, record):
        url = reverse('editors.review', args=[
            'unlisted',
            record.addon_slug if record.addon_slug is not None else record.id,
        ])
        self.increment_item()
        return safe_substitute(u'<a href="%s">%s <em>%s</em></a>',
                               url, record.addon_name, record.latest_version)

    def render_guid(self, record):
        return safe_substitute(u'%s', record.guid)

    def render_version_date(self, record):
        return safe_substitute(u'<span>%s</span>', record.version_date)

    def render_review_date(self, record):
        if record.review_version_num is None:
            return ugettext('No Reviews')
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


class AutoApprovedTable(EditorQueueTable):
    addon_name = tables.Column(verbose_name=_(u'Add-on'), accessor='name')
    # Override empty_values for flags so that they can be displayed even if the
    # model does not have a flags attribute.
    flags = tables.Column(
        verbose_name=_(u'Flags'), empty_values=(), orderable=False)
    last_human_review = tables.DateTimeColumn(
        verbose_name=_(u'Last Review'),
        accessor='addonapprovalscounter.last_human_review')
    weight = tables.Column(
        verbose_name=_(u'Weight'),
        accessor='_current_version.autoapprovalsummary.weight')

    class Meta(EditorQueueTable.Meta):
        fields = ('addon_name', 'flags', 'last_human_review', 'weight')
        # Exclude base fields EditorQueueTable has that we don't want.
        exclude = ('addon_type_id', 'waiting_time_min',)
        orderable = False

    def render_flags(self, record):
        return super(AutoApprovedTable, self).render_flags(
            record.current_version)

    def render_addon_name(self, record):
        url = reverse('editors.review', args=[record.slug])
        return u'<a href="%s">%s <em>%s</em></a>' % (
            url, jinja2.escape(record.name),
            jinja2.escape(record.current_version))

    def render_last_human_review(self, value):
        return naturaltime(value) if value else ''


log = olympia.core.logger.getLogger('z.mailer')


PENDING_STATUSES = (amo.STATUS_BETA, amo.STATUS_DISABLED, amo.STATUS_NULL,
                    amo.STATUS_PENDING, amo.STATUS_PUBLIC)


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
    elif addon.status in amo.VALID_ADDON_STATUSES:
        # Look at all add-on versions which have files awaiting review.
        qs = (Version.objects.filter(addon__disabled_by_user=False,
                                     files__status=amo.STATUS_AWAITING_REVIEW,
                                     addon__status=addon.status)
              .order_by('nomination', 'created').distinct()
              .no_transforms().values_list('addon_id', flat=True))
        position = 0
        for idx, addon_id in enumerate(qs, start=1):
            if addon_id == addon.id:
                position = idx
                break
        total = qs.count()
        if position:
            return {'pos': position, 'total': total}

    return False


class ReviewHelper(object):
    """
    A class that builds enough to render the form back to the user and
    process off to the correct handler.
    """
    def __init__(self, request=None, addon=None, version=None):
        self.handler = None
        self.required = {}
        self.addon = addon
        self.version = version
        self.get_review_type(request)
        self.actions = self.get_actions(request)

    def set_data(self, data):
        self.handler.set_data(data)

    def get_review_type(self, request):
        if (self.version and
                self.version.channel == amo.RELEASE_CHANNEL_UNLISTED):
            self.handler = ReviewUnlisted(
                request, self.addon, self.version, 'unlisted')
        elif self.addon.status == amo.STATUS_NOMINATED:
            self.handler = ReviewAddon(
                request, self.addon, self.version, 'nominated')
        else:
            self.handler = ReviewFiles(
                request, self.addon, self.version, 'pending')

    def get_actions(self, request):
        actions = OrderedDict()
        if request is None:
            # If request is not set, it means we are just (ab)using the
            # ReviewHelper for its `handler` attribute and we don't care about
            # the actions.
            return actions
        reviewable_because_complete = self.addon.status not in (
            amo.STATUS_NULL, amo.STATUS_DELETED)
        reviewable_because_admin = (
            not self.addon.admin_review or
            acl.action_allowed(request,
                               amo.permissions.REVIEWER_ADMIN_TOOLS_VIEW))
        reviewable_because_submission_time = (
            not is_limited_reviewer(request) or
            (self.version is not None and
                self.version.nomination is not None and
                (datetime.datetime.now() - self.version.nomination >=
                    datetime.timedelta(hours=REVIEW_LIMITED_DELAY_HOURS))))
        reviewable_because_pending = (
            self.version is not None and
            len(self.version.is_unreviewed) > 0)
        if (reviewable_because_complete and
                reviewable_because_admin and
                reviewable_because_submission_time and
                reviewable_because_pending):
            actions['public'] = {
                'method': self.handler.process_public,
                'minimal': False,
                'details': _('This will approve, sign, and publish this '
                             'version. The comments will be sent to the '
                             'developer.'),
                'label': _('Approve')}
            actions['reject'] = {
                'method': self.handler.process_sandbox,
                'label': _('Reject'),
                'details': _('This will reject this version and remove it '
                             'from the queue. The comments will be sent '
                             'to the developer.'),
                'minimal': False}
        if self.version:
            version_is_auto_approved_and_current = (
                self.version == self.addon.current_version and
                self.version.was_auto_approved)
            version_is_unlisted = (
                self.version.channel == amo.RELEASE_CHANNEL_UNLISTED)
            is_post_reviewer = acl.action_allowed(
                request, amo.permissions.ADDONS_POST_REVIEW)
            is_unlisted_reviewer = acl.action_allowed(
                request, amo.permissions.ADDONS_REVIEW_UNLISTED)

            # Post-reviewers and unlisted reviewers can confirm approval if
            # the version is unlisted or it's the current public version
            # and it was auto approved, respectively.
            if (is_unlisted_reviewer and version_is_unlisted) or (
                    is_post_reviewer and version_is_auto_approved_and_current):
                actions['confirm_auto_approved'] = {
                    'method': self.handler.confirm_auto_approved,
                    'label': _('Confirm Approval'),
                    'details': _('The latest public version of this '
                                 'add-on was automatically approved. This '
                                 'records your confirmation of the '
                                 'approval, without notifying the '
                                 'developer.'),
                    'minimal': True,
                    'comments': False,
                }
            # Post-reviewers can also reject multiple versions in one action on
            # the listed review page, if the add-on is public (it's useless if
            # the add-on is not public: that means there should only be one
            # version to reject at most).
            version_is_public_and_listed = (
                self.addon.status == amo.STATUS_PUBLIC and
                self.version.channel == amo.RELEASE_CHANNEL_LISTED)
            if is_post_reviewer and version_is_public_and_listed:
                actions['reject_multiple_versions'] = {
                    'method': self.handler.reject_multiple_versions,
                    'label': _('Reject Multiple Versions'),
                    'minimal': True,
                    'versions': True,
                    'details': _('This will reject the selected public '
                                 'versions. The comments will be sent to the '
                                 'developer.'),
                }
            actions['reply'] = {
                'method': self.handler.reviewer_reply,
                'label': _('Reviewer reply'),
                'details': _('This will send a message to the developer. '
                             'You will be notified when they reply.'),
                'minimal': True,
                'info_request': True}
            actions['super'] = {
                'method': self.handler.process_super_review,
                'label': _('Request super-review'),
                'details': _('If you have concerns about this add-on that '
                             'an admin reviewer should look into, enter '
                             'your comments in the area below. They will '
                             'not be sent to the developer.'),
                'minimal': True}
        actions['comment'] = {
            'method': self.handler.process_comment,
            'label': _('Comment'),
            'details': _('Make a comment on this version. The developer '
                         'won\'t be able to see this.'),
            'minimal': True,
            'info_request': self.version and self.version.has_info_request}

        return actions

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

    def set_data(self, data):
        self.data = data
        if 'addon_files' in data:
            self.files = data['addon_files']

    def set_files(self, status, files, hide_disabled_file=False):
        """Change the files to be the new status."""
        for file in files:
            file.datestatuschanged = datetime.datetime.now()
            file.reviewed = datetime.datetime.now()
            if hide_disabled_file:
                file.hide_disabled_file()
            file.status = status
            file.save()

    def log_action(self, action, version=None, files=None):
        details = {'comments': self.data['comments'],
                   'reviewtype': self.review_type}
        if files is None and self.files:
            files = self.files
        if files is not None:
            details['files'] = [f.id for f in files]
        if version is None and self.version:
            version = self.version
        if version is not None:
            details['version'] = version.version
            args = (self.addon, version)
        else:
            args = (self.addon,)

        kwargs = {'user': self.user, 'created': datetime.datetime.now(),
                  'details': details}
        ActivityLog.create(action, *args, **kwargs)

    def notify_email(self, template, subject,
                     perm_setting='editor_reviewed', version=None):
        """Notify the authors that their addon has been reviewed."""
        if version is None:
            version = self.version
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

        message = loader.get_template(
            'editors/emails/%s.ltxt' % template).render(
            Context(data, autoescape=False))
        send_activity_mail(
            subject, message, version, self.addon.authors.all(),
            settings.EDITORS_EMAIL, perm_setting=perm_setting)

    def get_context_data(self):
        addon_url = self.addon.get_url_path(add_prefix=False)
        # We need to display the name in some language that is relevant to the
        # recipient(s) instead of using the reviewer's. addon.default_locale
        # should work.
        if self.addon.name.locale != self.addon.default_locale:
            lang = to_language(self.addon.default_locale)
            with translation.override(lang):
                addon = Addon.unfiltered.get(pk=self.addon.pk)
        else:
            addon = self.addon
        review_url_kw = {'addon_id': self.addon.pk}
        if (self.version and
                self.version.channel == amo.RELEASE_CHANNEL_UNLISTED):
            review_url_kw['channel'] = 'unlisted'
            dev_ver_url = reverse(
                'devhub.addons.versions',
                args=[self.addon.id])
        else:
            dev_ver_url = self.addon.get_dev_url('versions')
        return {'name': addon.name,
                'number': self.version.version if self.version else '',
                'reviewer': self.user.display_name,
                'addon_url': absolutify(addon_url),
                'dev_versions_url': absolutify(dev_ver_url),
                'review_url': absolutify(reverse('editors.review',
                                                 kwargs=review_url_kw,
                                                 add_prefix=False)),
                'comments': self.data.get('comments'),
                'SITE_URL': settings.SITE_URL,
                'legacy_addon':
                    not self.files[0].is_webextension if self.files else False}

    def reviewer_reply(self):
        # Default to reviewer reply action.
        action = amo.LOG.REVIEWER_REPLY_VERSION
        if self.version:
            kw = {}
            info_request = self.data.get('info_request')
            if info_request is not None:
                # Update info request flag.
                kw['has_info_request'] = info_request
                if info_request:
                    # And change action to request info if set
                    action = amo.LOG.REQUEST_INFORMATION
            if (self.version.channel == amo.RELEASE_CHANNEL_UNLISTED and
                    not self.version.reviewed):
                kw['reviewed'] = datetime.datetime.now()
            self.version.update(**kw)

        log.info(u'Sending request for information for %s to authors and other'
                 u'recipients' % self.addon)
        log_and_notify(action, self.data['comments'],
                       self.user, self.version,
                       perm_setting='individual_contact',
                       detail_kwargs={'reviewtype': self.review_type})

    def process_comment(self):
        if self.version:
            kw = {'has_editor_comment': True}
            if not self.data.get('info_request'):
                kw['has_info_request'] = False
            if (self.version.channel == amo.RELEASE_CHANNEL_UNLISTED and
                    not self.version.reviewed):
                kw['reviewed'] = datetime.datetime.now()
            self.version.update(**kw)
        self.log_action(amo.LOG.COMMENT_VERSION)

    def process_public(self):
        """Set an add-on or a version to public."""
        # Safeguard to force implementation for unlisted add-ons to completely
        # override this method.
        assert self.version.channel == amo.RELEASE_CHANNEL_LISTED

        # Sign addon.
        for file_ in self.files:
            sign_file(file_, settings.SIGNING_SERVER)

        # Hold onto the status before we change it.
        status = self.addon.status

        # Save files first, because set_addon checks to make sure there
        # is at least one public file or it won't make the addon public.
        self.set_files(amo.STATUS_PUBLIC, self.files)
        if self.set_addon_status:
            self.set_addon(status=amo.STATUS_PUBLIC)

        # If we've approved a webextension, add a tag identifying them as such.
        if any(file_.is_webextension for file_ in self.files):
            Tag(tag_text='firefox57').save_tag(self.addon)

        # Increment approvals counter if we have a request (it means it's a
        # human doing the review) otherwise reset it as it's an automatic
        # approval.
        if self.request:
            AddonApprovalsCounter.increment_for_addon(addon=self.addon)
        else:
            AddonApprovalsCounter.reset_for_addon(addon=self.addon)

        self.log_action(amo.LOG.APPROVE_VERSION)
        template = u'%s_to_public' % self.review_type
        subject = u'Mozilla Add-ons: %s %s Approved'
        self.notify_email(template, subject)

        self.log_public_message()
        log.info(u'Sending email for %s' % (self.addon))

        # Assign reviewer incentive scores.
        if self.request:
            ReviewerScore.award_points(
                self.request.user, self.addon, status, version=self.version)

    def process_sandbox(self):
        """Set an addon or a version back to sandbox."""
        # Safeguard to force implementation for unlisted add-ons to completely
        # override this method.
        assert self.version.channel == amo.RELEASE_CHANNEL_LISTED

        # Hold onto the status before we change it.
        status = self.addon.status

        if self.set_addon_status:
            self.set_addon(status=amo.STATUS_NULL)
        self.set_files(amo.STATUS_DISABLED, self.files,
                       hide_disabled_file=True)

        self.log_action(amo.LOG.REJECT_VERSION)
        template = u'%s_to_sandbox' % self.review_type
        subject = u'Mozilla Add-ons: %s %s didn\'t pass review'
        self.notify_email(template, subject)

        self.log_sandbox_message()
        log.info(u'Sending email for %s' % (self.addon))

        # Assign reviewer incentive scores.
        if self.request:
            ReviewerScore.award_points(
                self.request.user, self.addon, status, version=self.version)

    def process_super_review(self):
        """Give an addon super review."""
        self.addon.update(admin_review=True)

        if not self.version.was_auto_approved:
            # Notify the developer unless the version has been auto-approved.
            self.notify_email(
                'author_super_review',
                u'Mozilla Add-ons: %s %s flagged for Admin Review')

        self.log_action(amo.LOG.REQUEST_SUPER_REVIEW)
        log.info(u'Super review requested for %s' % (self.addon))

    def confirm_auto_approved(self):
        """Confirm an auto-approval decision.

        We don't need to really store that information, what we care about
        is logging something for future reviewers to be aware of, and, if the
        version is listed, incrementing AddonApprovalsCounter, which also
        resets the last human review date to now, and log it so that it's
        displayed later in the review page."""
        if self.version.channel == amo.RELEASE_CHANNEL_LISTED:
            AddonApprovalsCounter.increment_for_addon(addon=self.addon)
        self.log_action(amo.LOG.CONFIRM_AUTO_APPROVED)

    def reject_multiple_versions(self):
        """Reject a list of versions."""
        # self.version and self.files won't point to the versions we want to
        # modify in this action, so set them to None before finding the right
        # versions.
        latest_version = self.version
        self.version = None
        self.files = None
        for version in self.data['versions']:
            files = version.files.all()
            self.set_files(amo.STATUS_DISABLED, files, hide_disabled_file=True)
            self.log_action(amo.LOG.REJECT_VERSION,
                            version=version, files=files)
        self.addon.update_status()
        self.data['version_numbers'] = u', '.join(
            unicode(v.version) for v in self.data['versions'])

        # Send the email to the developer. We need to pass the latest version
        # of the add-on instead of one of the versions we rejected, it will be
        # used to generate a token allowing the developer to reply, and that
        # only works with the latest version.
        template = u'reject_multiple_versions'
        subject = (u"Mozilla Add-ons: One or more versions of %s%s didn't "
                   u"pass review")
        self.notify_email(template, subject, version=latest_version)

        log.info(
            u'Making %s versions %s disabled' % (
                self.addon,
                u', '.join(unicode(v.pk) for v in self.data['versions'])))
        log.info(u'Sending email for %s' % (self.addon))


class ReviewAddon(ReviewBase):
    set_addon_status = True

    def log_public_message(self):
        log.info(u'Making %s public' % (self.addon))

    def log_sandbox_message(self):
        log.info(u'Making %s disabled' % (self.addon))


class ReviewFiles(ReviewBase):
    set_addon_status = False

    def log_public_message(self):
        log.info(u'Making %s files %s public' %
                 (self.addon, ', '.join([f.filename for f in self.files])))

    def log_sandbox_message(self):
        log.info(u'Making %s files %s disabled' %
                 (self.addon, ', '.join([f.filename for f in self.files])))


class ReviewUnlisted(ReviewBase):

    def process_public(self):
        """Set an unliste addon version files to public."""
        assert self.version.channel == amo.RELEASE_CHANNEL_UNLISTED

        # Sign addon.
        for file_ in self.files:
            sign_file(file_, settings.SIGNING_SERVER)

        self.set_files(amo.STATUS_PUBLIC, self.files)

        template = u'unlisted_to_reviewed_auto'
        subject = u'Mozilla Add-ons: %s %s signed and ready to download'
        self.log_action(amo.LOG.APPROVE_VERSION)
        self.notify_email(template, subject)

        log.info(u'Making %s files %s public' %
                 (self.addon, ', '.join([f.filename for f in self.files])))
        log.info(u'Sending email for %s' % (self.addon))


@register.function
@jinja2.contextfunction
def logs_tabnav_themes(context):
    """
    Returns tuple of tab navigation for the log pages.

    Each tuple contains three elements: (named url, tab_code, tab_text)
    """
    rv = [
        ('editors.themes.logs', 'themes', ugettext('Reviews'))
    ]
    if acl.action_allowed(context['request'],
                          amo.permissions.THEME_ADMIN_TOOLS_VIEW):
        rv.append(('editors.themes.deleted', 'deleted', ugettext('Deleted')))

    return rv


@register.function
@jinja2.contextfunction
def queue_tabnav_themes(context):
    """Similar to queue_tabnav, but for themes."""
    tabs = []
    if acl.action_allowed(context['request'], amo.permissions.THEMES_REVIEW):
        tabs.append((
            'editors.themes.list', 'pending_themes', ugettext('Pending'),
        ))
    if acl.action_allowed(context['request'],
                          amo.permissions.THEME_ADMIN_TOOLS_VIEW):
        tabs.append((
            'editors.themes.list_flagged',
            'flagged_themes',
            ugettext('Flagged'),
        ))
        tabs.append((
            'editors.themes.list_rereview', 'rereview_themes',
            ugettext('Updates'),
        ))
    return tabs


@register.function
@jinja2.contextfunction
def queue_tabnav_themes_interactive(context):
    """Tabnav for the interactive shiny theme queues."""
    tabs = []
    if acl.action_allowed(context['request'], amo.permissions.THEMES_REVIEW):
        tabs.append((
            'editors.themes.queue_themes', 'pending', ugettext('Pending'),
        ))
    if acl.action_allowed(context['request'],
                          amo.permissions.THEME_ADMIN_TOOLS_VIEW):
        tabs.append((
            'editors.themes.queue_flagged', 'flagged', ugettext('Flagged'),
        ))
        tabs.append((
            'editors.themes.queue_rereview', 'rereview', ugettext('Updates'),
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
