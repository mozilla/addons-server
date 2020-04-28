import random
from collections import OrderedDict
from datetime import datetime, timedelta

import django_tables2 as tables
import olympia.core.logger
from django.conf import settings
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.template import loader
from django.utils import translation
from django.utils.translation import ugettext_lazy as _, ungettext

from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.activity.utils import log_and_notify, send_activity_mail
from olympia.addons.models import (
    Addon, AddonApprovalsCounter, AddonReviewerFlags)
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import to_language
from olympia.constants.reviewers import REVIEWER_NEED_INFO_DAYS_DEFAULT
from olympia.discovery.models import DiscoveryItem
from olympia.lib.crypto.signing import sign_file
from olympia.reviewers.models import (
    AutoApprovalSummary, ReviewerScore, ViewUnlistedAllList, get_flags,
    get_flags_for_row)
from olympia.users.models import UserProfile
from olympia.versions.compare import addon_version_int

import jinja2


log = olympia.core.logger.getLogger('z.mailer')


class ItemStateTable(object):

    def increment_item(self):
        self.item_number += 1

    def set_page(self, page):
        self.item_number = page.start_index()


def safe_substitute(string, *args):
    return string % tuple(jinja2.escape(arg) for arg in args)


class ReviewerQueueTable(tables.Table, ItemStateTable):
    addon_name = tables.Column(verbose_name=_(u'Add-on'))
    addon_type_id = tables.Column(verbose_name=_(u'Type'))
    waiting_time_min = tables.Column(verbose_name=_(u'Waiting Time'))
    flags = tables.Column(verbose_name=_(u'Flags'), orderable=False)

    class Meta:
        orderable = True

    def render_addon_name(self, record):
        url = reverse('reviewers.review', args=[record.addon_slug])
        self.increment_item()
        return u'<a href="%s">%s <em>%s</em></a>' % (
            url, jinja2.escape(record.addon_name),
            jinja2.escape(record.latest_version))

    def render_addon_type_id(self, record):
        return amo.ADDON_TYPE[record.addon_type_id]

    def render_flags(self, record):
        if not hasattr(record, 'flags'):
            record.flags = get_flags_for_row(record)
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
    id = tables.Column(verbose_name=_('ID'))
    addon_name = tables.Column(verbose_name=_(u'Add-on'))
    guid = tables.Column(verbose_name=_(u'GUID'))
    authors = tables.Column(verbose_name=_(u'Authors'), orderable=False)

    class Meta(ReviewerQueueTable.Meta):
        model = ViewUnlistedAllList

    def render_addon_name(self, record):
        url = reverse('reviewers.review', args=[
            'unlisted',
            record.addon_slug if record.addon_slug is not None else record.id,
        ])
        self.increment_item()
        return safe_substitute(u'<a href="%s">%s</a>', url, record.addon_name)

    def render_guid(self, record):
        return safe_substitute(u'%s', record.guid)

    def render_authors(self, record):
        authors = record.authors
        if not len(authors):
            return ''
        more = ' '.join(
            safe_substitute(u'%s', uname) for (_, uname) in authors)
        author_links = ' '.join(
            safe_substitute(u'<a href="%s">%s</a>',
                            UserProfile.create_user_url(id_), uname)
            for (id_, uname) in authors[0:3])
        return u'<span title="%s">%s%s</span>' % (
            more, author_links, ' ...' if len(authors) > 3 else '')

    @classmethod
    def default_order_by(cls):
        return '-id'


def view_table_factory(viewqueue):

    class ViewQueueTable(ReviewerQueueTable):

        class Meta(ReviewerQueueTable.Meta):
            model = viewqueue

    return ViewQueueTable


class ModernAddonQueueTable(ReviewerQueueTable):
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

    class Meta(ReviewerQueueTable.Meta):
        fields = ('addon_name', 'flags', 'last_human_review', 'weight')
        # Exclude base fields ReviewerQueueTable has that we don't want.
        exclude = ('addon_type_id', 'waiting_time_min',)
        orderable = False

    def render_flags(self, record):
        if not hasattr(record, 'flags'):
            record.flags = get_flags(record, record.current_version)
        return super(ModernAddonQueueTable, self).render_flags(record)

    def _get_addon_name_url(self, record):
        return reverse('reviewers.review', args=[record.slug])

    def render_addon_name(self, record):
        url = self._get_addon_name_url(record)
        return u'<a href="%s">%s <em>%s</em></a>' % (
            url, jinja2.escape(record.name),
            jinja2.escape(record.current_version))

    def render_last_human_review(self, value):
        return naturaltime(value) if value else ''

    def render_weight(self, value):
        if value > amo.POST_REVIEW_WEIGHT_HIGHEST_RISK:
            classname = 'highest'
        elif value > amo.POST_REVIEW_WEIGHT_HIGH_RISK:
            classname = 'high'
        elif value > amo.POST_REVIEW_WEIGHT_MEDIUM_RISK:
            classname = 'medium'
        else:
            classname = 'low'

        return '<span class="risk-%s">%d</span>' % (classname, value)

    render_last_content_review = render_last_human_review


class ExpiredInfoRequestsTable(ModernAddonQueueTable):
    deadline = tables.Column(
        verbose_name=_(u'Information Request Deadline'),
        accessor='addonreviewerflags.pending_info_request')

    class Meta(ModernAddonQueueTable.Meta):
        fields = ('addon_name', 'flags', 'last_human_review', 'weight',
                  'deadline')

    def render_deadline(self, value):
        return naturaltime(value) if value else ''


class AutoApprovedTable(ModernAddonQueueTable):
    pass


class ContentReviewTable(AutoApprovedTable):
    last_updated = tables.DateTimeColumn(verbose_name=_(u'Last Updated'))

    class Meta(ReviewerQueueTable.Meta):
        fields = ('addon_name', 'flags', 'last_updated')
        # Exclude base fields ReviewerQueueTable has that we don't want.
        exclude = ('addon_type_id', 'last_human_review', 'waiting_time_min',
                   'weight')
        orderable = False

    def render_last_updated(self, value):
        return naturaltime(value) if value else ''

    def _get_addon_name_url(self, record):
        return reverse('reviewers.review', args=['content', record.slug])


class NeedsHumanReviewTable(AutoApprovedTable):
    def render_addon_name(self, record):
        rval = [jinja2.escape(record.name)]
        versions_flagged_by_scanners = record.versions.filter(
            channel=amo.RELEASE_CHANNEL_LISTED,
            needs_human_review=True).count()
        if versions_flagged_by_scanners:
            url = reverse('reviewers.review', args=[record.slug])
            rval.append(
                '<a href="%s">%s</a>' % (
                    url,
                    _('Listed versions needing human review ({0})').format(
                        versions_flagged_by_scanners)
                )
            )
        unlisted_versions_flagged_by_scanners = record.versions.filter(
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            needs_human_review=True).count()
        if unlisted_versions_flagged_by_scanners:
            url = reverse('reviewers.review', args=['unlisted', record.slug])
            rval.append(
                '<a href="%s">%s</a>' % (
                    url,
                    _('Unlisted versions needing human review ({0})').format(
                        unlisted_versions_flagged_by_scanners)
                )
            )
        return ''.join(rval)


class ReviewHelper(object):
    """
    A class that builds enough to render the form back to the user and
    process off to the correct handler.
    """
    def __init__(self, request=None, addon=None, version=None,
                 content_review=False):
        self.handler = None
        self.required = {}
        self.addon = addon
        self.version = version
        self.content_review = content_review
        self.set_review_handler(request)
        self.actions = self.get_actions(request)

    @property
    def redirect_url(self):
        return self.handler.redirect_url

    def set_data(self, data):
        self.handler.set_data(data)

    def set_review_handler(self, request):
        """Set the handler property."""
        if (self.version and
                self.version.channel == amo.RELEASE_CHANNEL_UNLISTED):
            self.handler = ReviewUnlisted(
                request, self.addon, self.version, 'unlisted',
                content_review=self.content_review)
        elif self.addon.status == amo.STATUS_NOMINATED:
            self.handler = ReviewAddon(
                request, self.addon, self.version, 'nominated',
                content_review=self.content_review)
        else:
            self.handler = ReviewFiles(
                request, self.addon, self.version, 'pending',
                content_review=self.content_review)

    def get_actions(self, request):
        actions = OrderedDict()
        if request is None:
            # If request is not set, it means we are just (ab)using the
            # ReviewHelper for its `handler` attribute and we don't care about
            # the actions.
            return actions

        # 2 kind of checks are made for the review page.
        # - Base permission checks to access the review page itself, done in
        #   the review() view
        # - A more specific check for each action, done below, restricting
        #   their availability while not affecting whether the user can see
        #   the review page or not.
        permission = None
        version_is_unlisted = (
            self.version and
            self.version.channel == amo.RELEASE_CHANNEL_UNLISTED)
        try:
            is_recommendable = self.addon.discoveryitem.recommendable
        except DiscoveryItem.DoesNotExist:
            is_recommendable = False
        current_version_is_listed_and_auto_approved = (
            self.version and
            self.version.channel == amo.RELEASE_CHANNEL_LISTED and
            self.addon.current_version and
            self.addon.current_version.was_auto_approved)

        if is_recommendable:
            is_admin_needed = (
                self.addon.needs_admin_content_review or
                self.addon.needs_admin_code_review)
            permission = amo.permissions.ADDONS_RECOMMENDED_REVIEW
        elif self.content_review:
            is_admin_needed = self.addon.needs_admin_content_review
            permission = amo.permissions.ADDONS_CONTENT_REVIEW
        elif version_is_unlisted:
            is_admin_needed = self.addon.needs_admin_code_review
            permission = amo.permissions.ADDONS_REVIEW_UNLISTED
        elif self.addon.type == amo.ADDON_STATICTHEME:
            is_admin_needed = self.addon.needs_admin_theme_review
            permission = amo.permissions.STATIC_THEMES_REVIEW
        elif current_version_is_listed_and_auto_approved:
            is_admin_needed = (
                self.addon.needs_admin_content_review or
                self.addon.needs_admin_code_review)
            permission = amo.permissions.ADDONS_POST_REVIEW
        else:
            is_admin_needed = (
                self.addon.needs_admin_content_review or
                self.addon.needs_admin_code_review)
            permission = amo.permissions.ADDONS_REVIEW

        assert permission is not None

        if is_admin_needed:
            permission = amo.permissions.REVIEWS_ADMIN

        # Is the current user a reviewer for this kind of add-on ?
        is_reviewer = acl.is_reviewer(request, self.addon)

        # Is the current user an appropriate reviewer, noy only for this kind
        # of add-on, but also for the state the add-on is in ? (Allows more
        # impactful actions).
        is_appropriate_reviewer = acl.action_allowed_user(
            request.user, permission)

        # Special logic for availability of reject multiple action:
        if (self.content_review or
                is_recommendable or
                self.addon.type == amo.ADDON_STATICTHEME):
            can_reject_multiple = is_appropriate_reviewer
        else:
            # When doing a code review, this action is also available to
            # users with Addons:PostReview even if the current version hasn't
            # been auto-approved, provided that the add-on isn't marked as
            # needing admin review.
            can_reject_multiple = (
                is_appropriate_reviewer or
                (acl.action_allowed_user(
                    request.user, amo.permissions.ADDONS_POST_REVIEW) and
                 not is_admin_needed)
            )

        addon_is_complete = self.addon.status not in (
            amo.STATUS_NULL, amo.STATUS_DELETED)
        version_is_unreviewed = self.version and self.version.is_unreviewed
        addon_is_valid = self.addon.is_public() or self.addon.is_unreviewed()
        addon_is_valid_and_version_is_listed = (
            addon_is_valid and
            self.version and
            self.version.channel == amo.RELEASE_CHANNEL_LISTED
        )

        # Definitions for all actions.
        actions['public'] = {
            'method': self.handler.process_public,
            'minimal': False,
            'details': _('This will approve, sign, and publish this '
                         'version. The comments will be sent to the '
                         'developer.'),
            'label': _('Approve'),
            'available': (
                not self.content_review and
                addon_is_complete and
                version_is_unreviewed and
                is_appropriate_reviewer
            )
        }
        actions['reject'] = {
            'method': self.handler.process_sandbox,
            'label': _('Reject'),
            'details': _('This will reject this version and remove it '
                         'from the queue. The comments will be sent '
                         'to the developer.'),
            'minimal': False,
            'available': (
                not self.content_review and
                addon_is_complete and
                version_is_unreviewed and
                is_appropriate_reviewer
            )
        }
        actions['approve_content'] = {
            'method': self.handler.approve_content,
            'label': _('Approve Content'),
            'details': _('This records your approbation of the '
                         'content of the latest public version, '
                         'without notifying the developer.'),
            'minimal': False,
            'comments': False,
            'available': (
                self.content_review and
                addon_is_valid_and_version_is_listed and
                is_appropriate_reviewer
            ),
        }
        actions['confirm_auto_approved'] = {
            'method': self.handler.confirm_auto_approved,
            'label': _('Confirm Approval'),
            'details': _('The latest public version of this add-on was '
                         'automatically approved. This records your '
                         'confirmation of the approval of that version, '
                         'without notifying the developer.'),
            'minimal': True,
            'comments': False,
            'available': (
                not self.content_review and
                addon_is_valid_and_version_is_listed and
                current_version_is_listed_and_auto_approved and
                is_appropriate_reviewer
            ),
        }
        actions['reject_multiple_versions'] = {
            'method': self.handler.reject_multiple_versions,
            'label': _('Reject Multiple Versions'),
            'minimal': True,
            'versions': True,
            'details': _('This will reject the selected public '
                         'versions. The comments will be sent to the '
                         'developer.'),
            'available': (
                addon_is_valid_and_version_is_listed and
                can_reject_multiple
            ),
        }
        actions['block_multiple_versions'] = {
            'method': self.handler.reject_multiple_versions,
            'label': _('Block Multiple Versions'),
            'minimal': True,
            'versions': True,
            'comments': False,
            'details': _('This will disable the selected approved '
                         'versions silently, and open up the block creation '
                         'admin page.'),
            'available': (
                self.addon.type != amo.ADDON_STATICTHEME and
                version_is_unlisted and
                is_appropriate_reviewer
            ),
        }
        actions['confirm_multiple_versions'] = {
            'method': self.handler.confirm_multiple_versions,
            'label': _('Confirm Multiple Versions'),
            'minimal': True,
            'versions': True,
            'details': _('This will confirm approval of the selected '
                         'versions without notifying the developer.'),
            'comments': False,
            'available': (
                self.addon.type != amo.ADDON_STATICTHEME and
                version_is_unlisted and
                is_appropriate_reviewer
            ),
        }
        actions['reply'] = {
            'method': self.handler.reviewer_reply,
            'label': _('Reviewer reply'),
            'details': _('This will send a message to the developer. '
                         'You will be notified when they reply.'),
            'minimal': True,
            'available': (
                self.version is not None and
                is_reviewer
            )
        }
        actions['super'] = {
            'method': self.handler.process_super_review,
            'label': _('Request super-review'),
            'details': _('If you have concerns about this add-on that '
                         'an admin reviewer should look into, enter '
                         'your comments in the area below. They will '
                         'not be sent to the developer.'),
            'minimal': True,
            'available': (
                self.version is not None and
                is_reviewer
            )
        }
        actions['comment'] = {
            'method': self.handler.process_comment,
            'label': _('Comment'),
            'details': _('Make a comment on this version. The developer '
                         'won\'t be able to see this.'),
            'minimal': True,
            'available': (
                is_reviewer
            )
        }

        return OrderedDict(
            ((key, action) for key, action in actions.items()
             if action['available'])
        )

    def process(self):
        action = self.handler.data.get('action', '')
        if not action:
            raise NotImplementedError
        return self.actions[action]['method']()


class ReviewBase(object):

    def __init__(self, request, addon, version, review_type,
                 content_review=False):
        self.request = request
        if request:
            self.user = self.request.user
            self.human_review = True
        else:
            # Use the addons team go-to user "Mozilla" for the automatic
            # validations.
            self.user = UserProfile.objects.get(pk=settings.TASK_USER_ID)
            self.human_review = False
        self.addon = addon
        self.version = version
        self.review_type = (
            ('theme_%s' if addon.type == amo.ADDON_STATICTHEME
             else 'extension_%s') % review_type)
        self.files = self.version.unreviewed_files if self.version else []
        self.content_review = content_review
        self.redirect_url = None

    def set_addon(self, **kw):
        """Alter addon, set reviewed timestamp on version being reviewed."""
        self.addon.update(**kw)
        self.version.update(reviewed=datetime.now())

    def set_data(self, data):
        self.data = data

    def set_files(self, status, files, hide_disabled_file=False):
        """Change the files to be the new status."""
        for file in files:
            file.datestatuschanged = datetime.now()
            file.reviewed = datetime.now()
            if hide_disabled_file:
                file.hide_disabled_file()
            file.status = status
            file.save()

    def set_recommended(self):
        try:
            item = self.addon.discoveryitem
        except DiscoveryItem.DoesNotExist:
            return
        if item.recommendable:
            # These addons shouldn't be be attempted for auto approval anyway,
            # but double check that the cron job isn't trying to approve it.
            assert not self.user.id == settings.TASK_USER_ID
            self.version.update(recommendation_approved=True)

    def unset_past_needs_human_review(self):
        """Clear needs_human_review flag on past listed versions.

        To be called when approving a listed version: For listed, the version
        reviewers are approving is always the latest listed one, and then users
        are supposed to automatically get the update to that version, so we
        don't need to care about older ones anymore.
        """
        # Do a mass UPDATE.
        self.addon.versions.filter(
            needs_human_review=True,
            channel=self.version.channel).update(
            needs_human_review=False)
        # Also reset it on self.version in case this instance is saved later.
        self.version.needs_human_review = False

    def log_action(self, action, version=None, files=None,
                   timestamp=None):
        details = {'comments': self.data['comments'],
                   'reviewtype': self.review_type.split('_')[1]}
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
        if timestamp is None:
            timestamp = datetime.now()

        kwargs = {'user': self.user, 'created': timestamp,
                  'details': details}
        self.log_entry = ActivityLog.create(action, *args, **kwargs)

    def notify_email(self, template, subject,
                     perm_setting='reviewer_reviewed', version=None):
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
        unique_id = (self.log_entry.id if hasattr(self, 'log_entry')
                     else random.randrange(100000))

        message = loader.get_template(
            'reviewers/emails/%s.ltxt' % template).render(data)
        send_activity_mail(
            subject, message, version, self.addon.authors.all(),
            settings.ADDONS_EMAIL, unique_id, perm_setting=perm_setting)

    def get_context_data(self):
        addon_url = self.addon.get_url_path(add_prefix=False)
        # We need to display the name in some language that is relevant to the
        # recipient(s) instead of using the reviewer's. addon.default_locale
        # should work.
        if (self.addon.name and
                self.addon.name.locale != self.addon.default_locale):
            lang = to_language(self.addon.default_locale)
            with translation.override(lang):
                # Force a reload of translations for this addon.
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
        return {'name': str(addon.name),
                'number': self.version.version if self.version else '',
                'reviewer': self.user.reviewer_name or self.user.name,
                'addon_url': absolutify(addon_url),
                'dev_versions_url': absolutify(dev_ver_url),
                'review_url': absolutify(reverse('reviewers.review',
                                                 kwargs=review_url_kw,
                                                 add_prefix=False)),
                'comments': self.data.get('comments'),
                'SITE_URL': settings.SITE_URL}

    def reviewer_reply(self):
        # Default to reviewer reply action.
        action = amo.LOG.REVIEWER_REPLY_VERSION
        if self.version:
            if (self.version.channel == amo.RELEASE_CHANNEL_UNLISTED and
                    not self.version.reviewed):
                self.version.update(reviewed=datetime.now())
            if self.data.get('info_request'):
                # It's an information request and not just a simple reply.
                # The ActivityLog will be different...
                action = amo.LOG.REQUEST_INFORMATION
                # And the deadline for the info request will be created or
                # updated x days in the future.
                info_request_deadline_days = int(
                    self.data.get('info_request_deadline',
                                  REVIEWER_NEED_INFO_DAYS_DEFAULT))
                info_request_deadline = (
                    datetime.now() + timedelta(days=info_request_deadline_days)
                )
                # Update or create the reviewer flags, overwriting
                # self.addon.addonreviewerflags with the one we
                # create/update so that we don't use an older version of it
                # later when notifying. Also, since this is a new request,
                # clear out the notified_about_expiring_info_request field.
                self.addon.addonreviewerflags = (
                    AddonReviewerFlags.objects.update_or_create(
                        addon=self.addon, defaults={
                            'pending_info_request': info_request_deadline,
                            'notified_about_expiring_info_request': False,
                        }
                    )[0]
                )

        log.info(u'Sending reviewer reply for %s to authors and other'
                 u'recipients' % self.addon)
        log_and_notify(
            action, self.data['comments'], self.user, self.version,
            perm_setting='individual_contact',
            detail_kwargs={'reviewtype': self.review_type.split('_')[1]})

    def sign_files(self):
        for file_ in self.files:
            if file_.is_experiment:
                ActivityLog.create(
                    amo.LOG.EXPERIMENT_SIGNED, file_, user=self.user)
            sign_file(file_)

    def process_comment(self):
        self.log_action(amo.LOG.COMMENT_VERSION)
        update_reviewed = (
            self.version and
            self.version.channel == amo.RELEASE_CHANNEL_UNLISTED and
            not self.version.reviewed)
        if update_reviewed:
            self.version.update(reviewed=datetime.now())

    def process_public(self):
        """Set an add-on or a version to public."""
        # Safeguard to force implementation for unlisted add-ons to completely
        # override this method.
        assert self.version.channel == amo.RELEASE_CHANNEL_LISTED

        # Safeguard to make sure this action is not used for content review
        # (it should use confirm_auto_approved instead).
        assert not self.content_review

        # Sign addon.
        self.sign_files()

        # Hold onto the status before we change it.
        status = self.addon.status

        # Save files first, because set_addon checks to make sure there
        # is at least one public file or it won't make the addon public.
        self.set_files(amo.STATUS_APPROVED, self.files)
        self.set_recommended()
        if self.set_addon_status:
            self.set_addon(status=amo.STATUS_APPROVED)

        # Clear needs_human_review flags on past listed versions.
        if self.human_review:
            self.unset_past_needs_human_review()

        # Increment approvals counter if we have a request (it means it's a
        # human doing the review) otherwise reset it as it's an automatic
        # approval.
        if self.human_review:
            AddonApprovalsCounter.increment_for_addon(addon=self.addon)
        else:
            AddonApprovalsCounter.reset_for_addon(addon=self.addon)

        self.log_action(amo.LOG.APPROVE_VERSION)
        template = u'%s_to_approved' % self.review_type
        if self.review_type in ['extension_pending', 'theme_pending']:
            subject = u'Mozilla Add-ons: %s %s Updated'
        else:
            subject = u'Mozilla Add-ons: %s %s Approved'
        self.notify_email(template, subject)

        self.log_public_message()
        log.info(u'Sending email for %s' % (self.addon))

        # Assign reviewer incentive scores.
        if self.human_review:
            ReviewerScore.award_points(
                self.user, self.addon, status, version=self.version)

    def process_sandbox(self):
        """Set an addon or a version back to sandbox."""
        # Safeguard to force implementation for unlisted add-ons to completely
        # override this method.
        assert self.version.channel == amo.RELEASE_CHANNEL_LISTED

        # Safeguard to make sure this action is not used for content review
        # (it should use reject_multiple_versions instead).
        assert not self.content_review

        # Hold onto the status before we change it.
        status = self.addon.status

        if self.set_addon_status:
            self.set_addon(status=amo.STATUS_NULL)
        self.set_files(amo.STATUS_DISABLED, self.files,
                       hide_disabled_file=True)

        # Unset needs_human_review on the latest version - it's the only
        # version we can be certain that the reviewer looked at.
        if self.human_review:
            self.version.update(needs_human_review=False)

        self.log_action(amo.LOG.REJECT_VERSION)
        template = u'%s_to_rejected' % self.review_type
        subject = u'Mozilla Add-ons: %s %s didn\'t pass review'
        self.notify_email(template, subject)

        self.log_sandbox_message()
        log.info(u'Sending email for %s' % (self.addon))

        # Assign reviewer incentive scores.
        if self.human_review:
            ReviewerScore.award_points(
                self.user, self.addon, status, version=self.version)

    def process_super_review(self):
        """Mark an add-on as needing admin code, content, or theme review."""
        addon_type = self.addon.type

        if addon_type == amo.ADDON_STATICTHEME:
            needs_admin_property = 'needs_admin_theme_review'
            log_action_type = amo.LOG.REQUEST_ADMIN_REVIEW_THEME
        elif self.content_review:
            needs_admin_property = 'needs_admin_content_review'
            log_action_type = amo.LOG.REQUEST_ADMIN_REVIEW_CONTENT
        else:
            needs_admin_property = 'needs_admin_code_review'
            log_action_type = amo.LOG.REQUEST_ADMIN_REVIEW_CODE

        AddonReviewerFlags.objects.update_or_create(
            addon=self.addon, defaults={needs_admin_property: True})

        self.log_action(log_action_type)
        log.info(u'%s for %s' % (log_action_type.short, self.addon))

    def approve_content(self):
        """Approve content of an add-on."""
        channel = self.version.channel
        version = self.addon.current_version

        # Content review only action.
        assert self.content_review

        # Doesn't make sense for unlisted versions.
        assert channel == amo.RELEASE_CHANNEL_LISTED

        # Like confirm auto approval, the approve content action should not
        # show the comment box, so override the text in case the reviewer
        # switched between actions and accidently submitted some comments from
        # another action.
        self.data['comments'] = ''

        # When doing a content review, don't increment the approvals counter,
        # just record the date of the content approval and log it.
        AddonApprovalsCounter.approve_content_for_addon(addon=self.addon)
        self.log_action(amo.LOG.APPROVE_CONTENT, version=version)

        # Assign reviewer incentive scores.
        if self.human_review:
            is_post_review = channel == amo.RELEASE_CHANNEL_LISTED
            ReviewerScore.award_points(
                self.user, self.addon, self.addon.status,
                version=version, post_review=is_post_review,
                content_review=self.content_review)

    def confirm_auto_approved(self):
        """Confirm an auto-approval decision."""

        channel = self.version.channel
        if channel == amo.RELEASE_CHANNEL_LISTED:
            # When doing an approval in listed channel, the version we care
            # about is always current_version and *not* self.version.
            # This allows reviewers to confirm approval of a public add-on even
            # when their latest version is disabled.
            version = self.addon.current_version
        else:
            # For unlisted, we just use self.version.
            version = self.version
        # The confirm auto-approval action should not show the comment box,
        # so override the text in case the reviewer switched between actions
        # and accidently submitted some comments from another action.
        self.data['comments'] = ''

        self.log_action(amo.LOG.CONFIRM_AUTO_APPROVED, version=version)

        if self.human_review:
            # Mark the approval as confirmed (handle DoesNotExist, it may have
            # been auto-approved before we unified workflow for unlisted and
            # listed).
            try:
                version.autoapprovalsummary.update(confirmed=True)
            except AutoApprovalSummary.DoesNotExist:
                pass

            if channel == amo.RELEASE_CHANNEL_LISTED:
                # Clear needs_human_review flags on past versions in channel.
                self.unset_past_needs_human_review()
                AddonApprovalsCounter.increment_for_addon(addon=self.addon)
            else:
                # For now, for unlisted versions, only drop the
                # needs_human_review flag on the latest version.
                if self.version.needs_human_review:
                    self.version.update(needs_human_review=False)

            is_post_review = channel == amo.RELEASE_CHANNEL_LISTED
            ReviewerScore.award_points(
                self.user, self.addon, self.addon.status,
                version=version, post_review=is_post_review,
                content_review=self.content_review)

    def reject_multiple_versions(self):
        """Reject a list of versions."""
        # self.version and self.files won't point to the versions we want to
        # modify in this action, so set them to None before finding the right
        # versions.
        status = self.addon.status
        latest_version = self.version
        self.version = None
        self.files = None
        action_id = (amo.LOG.REJECT_CONTENT if self.content_review
                     else amo.LOG.REJECT_VERSION)
        timestamp = datetime.now()
        for version in self.data['versions']:
            files = version.files.all()
            self.set_files(amo.STATUS_DISABLED, files, hide_disabled_file=True)
            self.log_action(action_id, version=version, files=files,
                            timestamp=timestamp)
            if self.human_review:
                # Unset needs_human_review on rejected versions, we consider
                # that the reviewer looked at them before rejecting.
                if version.needs_human_review:
                    version.update(needs_human_review=False)

        self.addon.update_status()
        self.data['version_numbers'] = u', '.join(
            str(v.version) for v in self.data['versions'])

        # Send the email to the developer. We need to pass the latest version
        # of the add-on instead of one of the versions we rejected, it will be
        # used to generate a token allowing the developer to reply, and that
        # only works with the latest version.
        if self.addon.status != amo.STATUS_APPROVED:
            template = u'reject_multiple_versions_disabled_addon'
            subject = (u'Mozilla Add-ons: %s%s has been disabled on '
                       u'addons.mozilla.org')
        else:
            template = u'reject_multiple_versions'
            subject = u'Mozilla Add-ons: Versions disabled for %s%s'
        self.notify_email(template, subject, version=latest_version)

        log.info(
            u'Making %s versions %s disabled' % (
                self.addon,
                u', '.join(str(v.pk) for v in self.data['versions'])))
        log.info(u'Sending email for %s' % (self.addon))

        # Assign reviewer incentive scores.
        if self.human_review:
            ReviewerScore.award_points(
                self.user, self.addon, status, version=latest_version,
                post_review=True, content_review=self.content_review)

    def confirm_multiple_versions(self):
        raise NotImplementedError  # only implemented for unlisted below.


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
        """Set an unlisted addon version files to public."""
        assert self.version.channel == amo.RELEASE_CHANNEL_UNLISTED

        # Sign addon.
        self.sign_files()
        for file_ in self.files:
            ActivityLog.create(amo.LOG.UNLISTED_SIGNED, file_, user=self.user)

        self.set_files(amo.STATUS_APPROVED, self.files)

        template = u'unlisted_to_reviewed_auto'
        subject = u'Mozilla Add-ons: %s %s signed and ready to download'
        self.log_action(amo.LOG.APPROVE_VERSION)

        self.notify_email(template, subject, perm_setting=None)

        log.info(u'Making %s files %s public' %
                 (self.addon, ', '.join([f.filename for f in self.files])))
        log.info(u'Sending email for %s' % (self.addon))

    def reject_multiple_versions(self):
        # self.version and self.files won't point to the versions we want to
        # modify in this action, so set them to None before finding the right
        # versions.
        self.version = None
        self.files = None
        action_id = amo.LOG.REJECT_VERSION
        timestamp = datetime.now()
        min_version = ('0', 0)
        max_version = ('*', 0)
        for version in self.data['versions']:
            files = version.files.all()
            self.set_files(amo.STATUS_DISABLED, files, hide_disabled_file=True)
            self.log_action(action_id, version=version, files=files,
                            timestamp=timestamp)
            if self.human_review:
                # Unset needs_human_review on rejected versions, we consider
                # that the reviewer looked at them before disabling.
                if version.needs_human_review:
                    version.update(needs_human_review=False)
            version_int = addon_version_int(version.version)
            if not min_version[1] or version_int < min_version[1]:
                min_version = (version, version_int)
            if not max_version[1] or version_int > max_version[1]:
                max_version = (version, version_int)
        log.info(
            'Making %s versions %s disabled' % (
                self.addon,
                ', '.join(str(v.pk) for v in self.data['versions'])))

        if self.addon.blocklistsubmission:
            self.redirect_url = (
                reverse(
                    'admin:blocklist_blocklistsubmission_change',
                    args=(self.addon.blocklistsubmission.pk,)
                ))
        else:
            params = (
                f'?min={min_version[0].pk}&max={max_version[0].pk}')
            self.redirect_url = (
                reverse(
                    'admin:blocklist_block_addaddon', args=(self.addon.pk,)
                ) + params)

    def confirm_multiple_versions(self):
        """Confirm approval on a list of versions."""
        # There shouldn't be any comments for this action.
        self.data['comments'] = ''

        timestamp = datetime.now()
        for version in self.data['versions']:
            self.log_action(amo.LOG.CONFIRM_AUTO_APPROVED, version=version,
                            timestamp=timestamp)
            if self.human_review:
                # Mark summary as confirmed if it exists.
                try:
                    version.autoapprovalsummary.update(confirmed=True)
                except AutoApprovalSummary.DoesNotExist:
                    pass
                # Unset needs_human_review on rejected versions, we consider
                # that the reviewer looked at all versions they are approving.
                if version.needs_human_review:
                    version.update(needs_human_review=False)
