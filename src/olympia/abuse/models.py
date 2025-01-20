from datetime import datetime, timedelta
from itertools import chain

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models import Exists, OuterRef, Q
from django.db.transaction import atomic
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.models import BaseQuerySet, ManagerBase, ModelBase
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.api.utils import APIChoicesWithNone
from olympia.bandwagon.models import Collection
from olympia.constants.abuse import (
    APPEAL_EXPIRATION_DAYS,
    DECISION_ACTIONS,
    ILLEGAL_CATEGORIES,
    ILLEGAL_SUBCATEGORIES,
)
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile
from olympia.versions.models import Version, VersionReviewerFlags

from .actions import (
    ContentActionAlreadyRemoved,
    ContentActionApproveInitialDecision,
    ContentActionApproveNoAction,
    ContentActionBanUser,
    ContentActionDeleteCollection,
    ContentActionDeleteRating,
    ContentActionDisableAddon,
    ContentActionForwardToLegal,
    ContentActionForwardToReviewers,
    ContentActionIgnore,
    ContentActionNotImplemented,
    ContentActionOverrideApprove,
    ContentActionRejectVersion,
    ContentActionRejectVersionDelayed,
    ContentActionTargetAppealApprove,
    ContentActionTargetAppealRemovalAffirmation,
)
from .cinder import (
    CinderAddon,
    CinderAddonHandledByReviewers,
    CinderCollection,
    CinderRating,
    CinderReport,
    CinderUnauthenticatedReporter,
    CinderUser,
)


log = olympia.core.logger.getLogger('z.abuse')


class CinderJobQuerySet(BaseQuerySet):
    def for_addon(self, addon):
        return self.filter(target_addon=addon).order_by('-pk')

    def unresolved(self):
        return self.filter(decision__isnull=True)

    def resolvable_in_reviewer_tools(self):
        return self.filter(resolvable_in_reviewer_tools=True)


class CinderJobManager(ManagerBase):
    _queryset_class = CinderJobQuerySet

    def for_addon(self, addon):
        return self.get_queryset().for_addon(addon)

    def unresolved(self):
        return self.get_queryset().unresolved()

    def resolvable_in_reviewer_tools(self):
        return self.get_queryset().resolvable_in_reviewer_tools()


class CinderJob(ModelBase):
    job_id = models.CharField(max_length=36, unique=True)
    target_addon = models.ForeignKey(
        to=Addon, blank=True, null=True, on_delete=models.deletion.SET_NULL
    )
    decision = models.OneToOneField(
        to='abuse.ContentDecision',
        null=True,
        on_delete=models.SET_NULL,
        related_name='cinder_job',
    )
    resolvable_in_reviewer_tools = models.BooleanField(default=None, null=True)
    forwarded_to_job = models.ForeignKey(
        to='self',
        null=True,
        on_delete=models.SET_NULL,
        related_name='forwarded_from_jobs',
    )

    objects = CinderJobManager()

    @property
    def target(self):
        if self.target_addon_id:
            # if this was a job from an abuse report for an addon we've set target_addon
            return self.target_addon
        if self.decision:
            # if there is already a decision target will be set there
            return self.decision.target
        if self.is_appeal:
            # if this is an appeal job the decision will have the target
            return self.appealed_decisions.first().target
        else:
            # otherwise, look in the initial abuse report for the target
            # this works because all reports for a single job are for the same target.
            if initial_report := self.abusereport_set.first():
                return initial_report.target
            return None

    @property
    def final_decision(self):
        return (
            self.decision
            if not self.decision or not hasattr(self.decision, 'overridden_by')
            else self.decision.overridden_by
        )

    @property
    def all_abuse_reports(self):
        return [
            *chain.from_iterable(
                decision.originating_job.all_abuse_reports
                for decision in self.appealed_decisions.filter(
                    Q(cinder_job__isnull=False)
                    | Q(override_of__cinder_job__isnull=False)
                )
            ),
            *self.abusereport_set.all(),
        ]

    @property
    def is_appeal(self):
        return bool(self.appealed_decisions.exists())

    @classmethod
    def get_entity_helper(
        cls, target, *, resolved_in_reviewer_tools, addon_version_string=None
    ):
        if isinstance(target, Addon):
            if resolved_in_reviewer_tools:
                return CinderAddonHandledByReviewers(
                    target, version_string=addon_version_string
                )
            else:
                return CinderAddon(target)
        elif isinstance(target, UserProfile):
            return CinderUser(target)
        elif isinstance(target, Rating):
            return CinderRating(target)
        elif isinstance(target, Collection):
            return CinderCollection(target)

    @classmethod
    def get_cinder_reporter(cls, abuse):
        reporter = None
        if abuse.reporter:
            reporter = CinderUser(abuse.reporter)
        elif abuse.reporter_name or abuse.reporter_email:
            reporter = CinderUnauthenticatedReporter(
                abuse.reporter_name, abuse.reporter_email
            )
        return reporter

    @classmethod
    def handle_already_removed(cls, abuse_report):
        entity_helper = cls.get_entity_helper(
            abuse_report.target,
            addon_version_string=abuse_report.addon_version,
            resolved_in_reviewer_tools=False,
        )
        decision = ContentDecision.objects.create(
            addon=abuse_report.addon,
            rating=abuse_report.rating,
            collection=abuse_report.collection,
            user=abuse_report.user,
            action=DECISION_ACTIONS.AMO_CLOSED_NO_ACTION,
            action_date=datetime.now(),
            cinder_id=entity_helper.create_decision(
                action=DECISION_ACTIONS.AMO_CLOSED_NO_ACTION.api_value,
                reasoning='',
                policy_uuids=(),
            ),
        )
        decision.get_action_helper().notify_reporters(
            reporter_abuse_reports=[abuse_report], is_appeal=False
        )

    @classmethod
    def report(cls, abuse_report):
        target = abuse_report.target
        if (
            getattr(target, 'deleted', False)
            or getattr(target, 'banned', False)
            or getattr(target, 'status', -1) == amo.STATUS_DISABLED
        ):
            cls.handle_already_removed(abuse_report)
            return
        report_entity = CinderReport(abuse_report)
        reporter_entity = cls.get_cinder_reporter(abuse_report)
        entity_helper = cls.get_entity_helper(
            abuse_report.target,
            addon_version_string=abuse_report.addon_version,
            resolved_in_reviewer_tools=abuse_report.is_handled_by_reviewers,
        )
        job_id = entity_helper.report(report=report_entity, reporter=reporter_entity)
        defaults = {
            'target_addon': target if isinstance(target, Addon) else None,
            'resolvable_in_reviewer_tools': abuse_report.is_handled_by_reviewers,
        }
        with atomic():
            cinder_job, _ = cls.objects.get_or_create(job_id=job_id, defaults=defaults)
            abuse_report.update(cinder_job=cinder_job)
        # Additional context can take a while, so it is reported outside the
        # atomic() block so that the transaction can be committed quickly,
        # ensuring the CinderJob exists as soon as possible (we need it to
        # process any decisions). We don't need the database anymore at this
        # point anyway.
        entity_helper.report_additional_context()

        if cinder_job.decision and (
            cinder_job.decision.action
            == DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON
        ):
            # if this is a new report, it's never an appeal
            cinder_job.decision.get_action_helper().notify_reporters(
                reporter_abuse_reports=[abuse_report], is_appeal=False
            )

        entity_helper.post_report(job=cinder_job)

    def notify_reporters(self, action_helper):
        action_helper.notify_reporters(
            reporter_abuse_reports=self.abusereport_set.all(),
            is_appeal=False,
        )
        appellants = AbuseReport.objects.filter(
            cinderappeal__decision__in=self.appealed_decisions.all()
        )
        action_helper.notify_reporters(
            reporter_abuse_reports=appellants, is_appeal=True
        )

    def handle_job_recreated(self, *, new_job_id, resolvable_in_reviewer_tools):
        from olympia.reviewers.models import NeedsHumanReview

        new_job, created = CinderJob.objects.update_or_create(
            job_id=new_job_id,
            defaults={
                'resolvable_in_reviewer_tools': resolvable_in_reviewer_tools,
                'target_addon': self.target_addon,
            },
        )
        # If this forward has been combined with an existing non-forwarded job we need
        # to clear the NHR for reason:ABUSE_ADDON_VIOLATION, because it now has a NHR
        # for reason:CINDER_ESCALATION.
        if not created and not new_job.forwarded_from_jobs.exists():
            has_unresolved_abuse_report_jobs = (
                self.__class__.objects.for_addon(new_job.target_addon)
                .exclude(
                    id=new_job.id,
                    forwarded_from_jobs__isnull=True,
                    appealed_decisions__isnull=True,
                )
                .unresolved()
                .resolvable_in_reviewer_tools()
                .exists()
            )
            # But only if there aren't other jobs that should legitimately have a NHR
            # for reason:ABUSE_ADDON_VIOLATION
            if not has_unresolved_abuse_report_jobs:
                NeedsHumanReview.objects.filter(
                    version__addon_id=new_job.target_addon.id,
                    is_active=True,
                    reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION,
                ).update(is_active=False)
                new_job.target_addon.update_all_due_dates()
        # Update our fks to connected objects
        AbuseReport.objects.filter(cinder_job=self).update(cinder_job=new_job)
        ContentDecision.objects.filter(appeal_job=self).update(appeal_job=new_job)
        self.update(forwarded_to_job=new_job)

    def process_decision(
        self,
        *,
        decision_cinder_id,
        decision_action,
        decision_notes,
        policy_ids,
    ):
        """This is called for cinder originated decisions only."""
        # We need either an AbuseReport or ContentDecision for the target props
        abuse_report_or_decision = (
            self.appealed_decisions.first() or self.abusereport_set.first()
        )
        decision = ContentDecision.objects.create(
            addon=(
                self.target_addon
                if self.target_addon_id
                else abuse_report_or_decision.addon
            ),
            rating=abuse_report_or_decision.rating,
            collection=abuse_report_or_decision.collection,
            user=abuse_report_or_decision.user,
            cinder_id=decision_cinder_id,
            action=decision_action,
            notes=decision_notes[: ContentDecision._meta.get_field('notes').max_length],
            override_of=self.decision,
        )
        policies = CinderPolicy.objects.filter(
            uuid__in=policy_ids
        ).without_parents_if_their_children_are_present()
        decision.policies.add(*policies)

        if not self.decision:
            self.update(decision=decision)

        # no need to report - it came from Cinder
        decision.execute_action()
        decision.send_notifications()

    def process_queue_move(self, *, new_queue, notes):
        CinderQueueMove.objects.create(cinder_job=self, notes=notes, to_queue=new_queue)
        if new_queue == CinderAddonHandledByReviewers(self.target).queue:
            # now escalated
            entity_helper = CinderJob.get_entity_helper(
                self.target, resolved_in_reviewer_tools=True
            )
            entity_helper.post_queue_move(job=self)
            self.update(resolvable_in_reviewer_tools=True)
        elif self.resolvable_in_reviewer_tools:
            # now not escalated
            log.debug(
                'Job %s has moved out of AMO handled queue, but this is not yet '
                'supported',
                self.id,
            )
        else:
            log.debug(
                'Job %s has moved, but not in or out of AMO handled queue', self.id
            )

    def clear_needs_human_review_flags(self):
        from olympia.reviewers.models import NeedsHumanReview

        # We don't want to clear a NeedsHumanReview caused by a job that
        # isn't resolved yet, but there is no link between NHR and jobs.
        # So for each possible reason, we look if there are unresolved jobs
        # and only clear NHR for that reason if there aren't any jobs left.
        addon = self.decision.addon
        base_unresolved_jobs_qs = (
            self.__class__.objects.for_addon(addon)
            .unresolved()
            .resolvable_in_reviewer_tools()
        )
        if self.forwarded_from_jobs.exists():
            has_unresolved_jobs_with_similar_reason = base_unresolved_jobs_qs.filter(
                forwarded_from_jobs__isnull=False
            ).exists()
            reasons = {
                NeedsHumanReview.REASONS.CINDER_ESCALATION,
                NeedsHumanReview.REASONS.CINDER_APPEAL_ESCALATION,
            }
        elif self.queue_moves.exists():
            has_unresolved_jobs_with_similar_reason = base_unresolved_jobs_qs.filter(
                queue_moves__id__gt=0
            ).exists()
            reasons = {
                NeedsHumanReview.REASONS.CINDER_ESCALATION,
                NeedsHumanReview.REASONS.CINDER_APPEAL_ESCALATION,
            }
        elif self.is_appeal:
            has_unresolved_jobs_with_similar_reason = base_unresolved_jobs_qs.filter(
                appealed_decisions__isnull=False
            ).exists()
            reasons = {NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL}
        else:
            # If the job we're resolving was not an appeal or escalation
            # then all abuse reports are considered dealt with.
            has_unresolved_jobs_with_similar_reason = None
            reasons = {NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION}
        if not has_unresolved_jobs_with_similar_reason:
            NeedsHumanReview.objects.filter(
                version__addon_id=addon.id, is_active=True, reason__in=reasons
            ).update(is_active=False)
            addon.update_all_due_dates()


class AbuseReportQuerySet(BaseQuerySet):
    def for_addon(self, addon):
        return (
            self.filter(
                models.Q(guid=addon.addonguid_guid)
                | models.Q(user__in=addon.listed_authors)
            )
            .select_related('user')
            .order_by('-created')
        )


class AbuseReportManager(ManagerBase):
    _queryset_class = AbuseReportQuerySet

    def for_addon(self, addon):
        return self.get_queryset().for_addon(addon)

    @classmethod
    def is_individually_actionable_q(cls):
        """A Q object to filter on Abuse reports reportable under DSA, so should be sent
        to Cinder."""
        current_version = Addon.objects.filter(
            guid=OuterRef('guid'), _current_version__isnull=False
        )
        listed_version = Version.unfiltered.filter(
            addon__guid=OuterRef('guid'),
            version=OuterRef('addon_version'),
            channel=amo.CHANNEL_LISTED,
        )
        not_addon = Q(guid__isnull=True)
        current_or_version_exists = Exists(listed_version) | (
            (Q(addon_version='') | Q(addon_version__isnull=True))
            & Exists(current_version)
        )
        return Q(
            not_addon | current_or_version_exists,
            reason__in=AbuseReport.REASONS.INDIVIDUALLY_ACTIONABLE_REASONS.values,
        )


class AbuseReport(ModelBase):
    # Note: those choices don't need to be translated for now, the
    # human-readable values are only exposed in the admin.
    ADDON_SIGNATURES = APIChoicesWithNone(
        ('CURATED_AND_PARTNER', 1, 'Curated and partner'),
        ('CURATED', 2, 'Curated'),
        ('PARTNER', 3, 'Partner'),
        ('NON_CURATED', 4, 'Non-curated'),
        ('UNSIGNED', 5, 'Unsigned'),
        ('BROKEN', 6, 'Broken'),
        ('UNKNOWN', 7, 'Unknown'),
        ('MISSING', 8, 'Missing'),
        ('PRELIMINARY', 9, 'Preliminary'),
        ('SIGNED', 10, 'Signed'),
        ('SYSTEM', 11, 'System'),
        ('PRIVILEGED', 12, 'Privileged'),
        ('NOT_REQUIRED', 13, 'Not required'),
    )
    REASONS = APIChoicesWithNone(
        # Reporting reasons used in Firefox
        ('DAMAGE', 1, 'Damages computer and/or data'),
        ('SPAM', 2, 'Creates spam or advertising'),
        (
            'SETTINGS',
            3,
            'Changes search / homepage / new tab page without informing user',
        ),
        # `4` was previously 'New tab takeover' but has been merged into the
        # previous one. We avoid re-using the value.
        ('BROKEN', 5, 'Doesn’t work, breaks websites, or slows Firefox down'),
        ('POLICY', 6, 'Hateful, violent, or illegal content'),
        ('DECEPTIVE', 7, 'Pretends to be something it’s not'),
        # `8` was previously "Doesn't work" but has been merged into the
        # previous one. We avoid re-using the value.
        ('UNWANTED', 9, "Wasn't wanted / impossible to get rid of"),
        # `10` was previously "Other". We avoid re-using the value.
        #
        # Reporting reasons used in AMO Feedback flow - DSA categories
        (
            'HATEFUL_VIOLENT_DECEPTIVE',
            11,
            'DSA: It contains hateful, violent, deceptive, or other inappropriate '
            'content',
        ),
        (
            'ILLEGAL',
            12,
            'DSA: It violates the law or contains content that violates the law',
        ),
        ('POLICY_VIOLATION', 13, "DSA: It violates Mozilla's Add-on Policies"),
        ('SOMETHING_ELSE', 14, 'DSA: Something else'),
        # Reporting reasons used in AMO Feedback flow - Feedback (non-DSA) categories
        (
            'DOES_NOT_WORK',
            20,
            'Feedback: It does not work, breaks websites, or slows down Firefox',
        ),
        (
            'FEEDBACK_SPAM',
            21,
            "Feedback: It's spam",
        ),
        ('OTHER', 127, 'Other'),
    )
    # Base reasons shared by all on-AMO content using AMO Feedback flow.
    REASONS.add_subset(
        'CONTENT_REASONS',
        ('HATEFUL_VIOLENT_DECEPTIVE', 'ILLEGAL', 'FEEDBACK_SPAM', 'SOMETHING_ELSE'),
    )
    # Those reasons will be reported to Cinder.
    REASONS.add_subset(
        'INDIVIDUALLY_ACTIONABLE_REASONS',
        ('HATEFUL_VIOLENT_DECEPTIVE', 'ILLEGAL', 'POLICY_VIOLATION', 'SOMETHING_ELSE'),
    )
    # Abuse in these locations are handled by reviewers
    REASONS.add_subset('REVIEWER_HANDLED', ('POLICY_VIOLATION',))

    # https://searchfox.org
    # /mozilla-central/source/toolkit/components/telemetry/Events.yaml#122-131
    # Firefox submits values in lowercase, with '-' and ':' changed to '_'.
    ADDON_INSTALL_METHODS = APIChoicesWithNone(
        ('AMWEBAPI', 1, 'Add-on Manager Web API'),
        ('LINK', 2, 'Direct link'),
        ('INSTALLTRIGGER', 3, 'Install Trigger'),
        ('INSTALL_FROM_FILE', 4, 'From File'),
        ('MANAGEMENT_WEBEXT_API', 5, 'Webext management API'),
        ('DRAG_AND_DROP', 6, 'Drag & Drop'),
        ('SIDELOAD', 7, 'Sideload'),
        # Values between 8 and 13 are obsolete, we use to merge
        # install source and method into addon_install_method before deciding
        # to split the two like Firefox does, so these 6 values are only kept
        # for backwards-compatibility with older reports and older versions of
        # Firefox that still only submit that.
        ('FILE_URL', 8, 'File URL'),
        ('ENTERPRISE_POLICY', 9, 'Enterprise Policy'),
        ('DISTRIBUTION', 10, 'Included in build'),
        ('SYSTEM_ADDON', 11, 'System Add-on'),
        ('TEMPORARY_ADDON', 12, 'Temporary Add-on'),
        ('SYNC', 13, 'Sync'),
        # Back to normal values.
        ('URL', 14, 'URL'),
        # Our own catch-all. The serializer expects it to be called "OTHER".
        ('OTHER', 127, 'Other'),
    )
    ADDON_INSTALL_SOURCES = APIChoicesWithNone(
        ('ABOUT_ADDONS', 1, 'Add-ons Manager'),
        ('ABOUT_DEBUGGING', 2, 'Add-ons Debugging'),
        ('ABOUT_PREFERENCES', 3, 'Preferences'),
        ('AMO', 4, 'AMO'),
        ('APP_PROFILE', 5, 'App Profile'),
        ('DISCO', 6, 'Disco Pane'),
        ('DISTRIBUTION', 7, 'Included in build'),
        ('EXTENSION', 8, 'Extension'),
        ('ENTERPRISE_POLICY', 9, 'Enterprise Policy'),
        ('FILE_URL', 10, 'File URL'),
        ('GMP_PLUGIN', 11, 'GMP Plugin'),
        ('INTERNAL', 12, 'Internal'),
        ('PLUGIN', 13, 'Plugin'),
        ('RTAMO', 14, 'Return to AMO'),
        ('SYNC', 15, 'Sync'),
        ('SYSTEM_ADDON', 16, 'System Add-on'),
        ('TEMPORARY_ADDON', 17, 'Temporary Add-on'),
        ('UNKNOWN', 18, 'Unknown'),
        ('WINREG_APP_USER', 19, 'Windows Registry (User)'),
        ('WINREG_APP_GLOBAL', 20, 'Windows Registry (Global)'),
        ('APP_SYSTEM_PROFILE', 21, 'System Add-on (Profile)'),
        ('APP_SYSTEM_ADDONS', 22, 'System Add-on (Update)'),
        ('APP_SYSTEM_DEFAULTS', 23, 'System Add-on (Bundled)'),
        ('APP_BUILTIN', 24, 'Built-in Add-on'),
        ('APP_SYSTEM_USER', 25, 'System-wide Add-on (User)'),
        ('APP_GLOBAL', 26, 'Application Add-on'),
        ('APP_SYSTEM_SHARE', 27, 'System-wide Add-on (OS Share)'),
        ('APP_SYSTEM_LOCAL', 28, 'System-wide Add-on (OS Local)'),
        # Our own catch-all. The serializer expects it to be called "OTHER".
        ('OTHER', 127, 'Other'),
    )
    REPORT_ENTRY_POINTS = APIChoicesWithNone(
        ('UNINSTALL', 1, 'Uninstall'),
        ('MENU', 2, 'Menu'),
        ('TOOLBAR_CONTEXT_MENU', 3, 'Toolbar context menu'),
        ('AMO', 4, 'AMO'),
        ('UNIFIED_CONTEXT_MENU', 5, 'Unified extensions context menu'),
    )
    LOCATION = APIChoicesWithNone(
        ('AMO', 1, 'Add-on page on AMO'),
        ('ADDON', 2, 'Inside Add-on'),
        ('BOTH', 3, 'Both on AMO and inside Add-on'),
    )
    # Abuse in these locations are handled by reviewers
    LOCATION.add_subset('REVIEWER_HANDLED', ('ADDON', 'BOTH'))

    # NULL if the reporter was not authenticated.
    reporter = models.ForeignKey(
        UserProfile,
        null=True,
        blank=True,
        related_name='abuse_reported',
        on_delete=models.SET_NULL,
        help_text='The user who submitted the report, if authenticated.',
    )
    # name and/or email can be provided instead for unauthenticated reporters
    reporter_email = models.CharField(
        max_length=255,
        default=None,
        null=True,
        help_text='The provided email of the reporter, if not authenticated.',
    )
    reporter_name = models.CharField(
        max_length=255,
        default=None,
        null=True,
        help_text='The provided name of the reporter, if not authenticated.',
    )
    country_code = models.CharField(max_length=2, default=None, null=True)
    # An abuse report can be for an addon, a user or a rating.
    # - If user is set then guid and rating should be null.
    # - If guid is set then user and rating should be null.
    # - If rating is set then user and guid should be null.
    guid = models.CharField(max_length=255, null=True)
    user = models.ForeignKey(
        UserProfile, null=True, related_name='abuse_reports', on_delete=models.SET_NULL
    )
    rating = models.ForeignKey(
        Rating, null=True, related_name='abuse_reports', on_delete=models.SET_NULL
    )
    collection = models.ForeignKey(
        Collection, null=True, related_name='abuse_reports', on_delete=models.SET_NULL
    )
    message = models.TextField(
        blank=True, help_text='The body/content of the abuse report.'
    )

    # Extra optional fields for more information, giving some context that is
    # meant to be extracted automatically by the client (i.e. Firefox) and
    # submitted via the API.
    client_id = models.CharField(
        default=None,
        max_length=64,
        blank=True,
        null=True,
        help_text="The client's hashed telemetry ID.",
    )
    addon_name = models.CharField(
        default=None,
        max_length=255,
        blank=True,
        null=True,
        help_text='The add-on name in the locale used by the client.',
    )
    addon_summary = models.CharField(
        default=None,
        max_length=255,
        blank=True,
        null=True,
        help_text='The add-on summary in the locale used by the client.',
    )
    addon_version = models.CharField(
        default=None, max_length=255, blank=True, null=True
    )
    addon_signature = models.PositiveSmallIntegerField(
        default=None, choices=ADDON_SIGNATURES.choices, blank=True, null=True
    )
    application = models.PositiveSmallIntegerField(
        default=amo.FIREFOX.id, choices=amo.APPS_CHOICES, blank=True, null=True
    )
    application_version = models.CharField(
        default=None, max_length=255, blank=True, null=True
    )
    application_locale = models.CharField(
        default=None, max_length=255, blank=True, null=True
    )
    operating_system = models.CharField(
        default=None, max_length=255, blank=True, null=True
    )
    operating_system_version = models.CharField(
        default=None, max_length=255, blank=True, null=True
    )
    install_date = models.DateTimeField(default=None, blank=True, null=True)
    reason = models.PositiveSmallIntegerField(
        default=None, choices=REASONS.choices, blank=True, null=True
    )
    addon_install_origin = models.CharField(
        # Supposed to be an URL, but the scheme could be moz-foo: or something
        # like that, and it's potentially truncated, so use a CharField and not
        # a URLField. We also don't want to automatically turn this into a
        # clickable link in the admin in case it's dangerous.
        default=None,
        max_length=255,
        blank=True,
        null=True,
    )
    addon_install_method = models.PositiveSmallIntegerField(
        default=None,
        choices=ADDON_INSTALL_METHODS.choices,
        blank=True,
        null=True,
        help_text=(
            'For addon_install_method and addon_install_source specifically,'
            'if an unsupported value is sent, it will be silently changed to other'
            'instead of raising a 400 error.'
        ),
    )
    addon_install_source = models.PositiveSmallIntegerField(
        default=None,
        choices=ADDON_INSTALL_SOURCES.choices,
        blank=True,
        null=True,
        help_text=(
            'For addon_install_method and addon_install_source specifically,'
            'if an unsupported value is sent, it will be silently changed to other'
            'instead of raising a 400 error.'
        ),
    )
    addon_install_source_url = models.CharField(
        # See addon_install_origin above as for why it's not an URLField.
        default=None,
        max_length=255,
        blank=True,
        null=True,
    )
    report_entry_point = models.PositiveSmallIntegerField(
        default=None, choices=REPORT_ENTRY_POINTS.choices, blank=True, null=True
    )
    location = models.PositiveSmallIntegerField(
        default=None,
        choices=LOCATION.choices,
        blank=True,
        null=True,
        help_text=(
            'Where the content being reported is located - on AMO or inside the add-on.'
        ),
    )
    cinder_job = models.ForeignKey(CinderJob, null=True, on_delete=models.SET_NULL)
    illegal_category = models.PositiveSmallIntegerField(
        default=None,
        choices=ILLEGAL_CATEGORIES.choices,
        blank=True,
        null=True,
        help_text='Type of illegal content',
    )
    illegal_subcategory = models.PositiveSmallIntegerField(
        default=None,
        choices=ILLEGAL_SUBCATEGORIES.choices,
        blank=True,
        null=True,
        help_text='Specific violation of illegal content',
    )

    objects = AbuseReportManager()

    class Meta:
        db_table = 'abuse_reports'
        indexes = [
            models.Index(fields=('created',), name='abuse_reports_created_idx'),
            models.Index(fields=('guid',), name='guid_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                name='just_one_of_guid_user_rating_collection_must_be_set',
                check=(
                    # Abuse is against...
                    # a guid
                    models.Q(
                        ~models.Q(guid=''),
                        guid__isnull=False,
                        user__isnull=True,
                        rating__isnull=True,
                        collection__isnull=True,
                    )
                    # or a user
                    | models.Q(
                        guid__isnull=True,
                        user__isnull=False,
                        rating__isnull=True,
                        collection__isnull=True,
                    )
                    # or a rating
                    | models.Q(
                        guid__isnull=True,
                        user__isnull=True,
                        rating__isnull=False,
                        collection__isnull=True,
                    )
                    # or a collection
                    | models.Q(
                        guid__isnull=True,
                        user__isnull=True,
                        rating__isnull=True,
                        collection__isnull=False,
                    )
                ),
            ),
        ]

    @property
    def type(self):
        if self.guid:
            type_ = 'Addon'
        elif self.user_id:
            type_ = 'User'
        elif self.rating_id:
            type_ = 'Rating'
        elif self.collection_id:
            type_ = 'Collection'
        else:
            type_ = 'Unknown'
        return type_

    def __str__(self):
        name = self.guid or self.user_id or self.rating_id or self.collection_id
        return f'Abuse Report for {self.type} {name}'

    @cached_property
    def addon(self):
        from olympia.addons.models import Addon

        if self.guid:
            return Addon.unfiltered.filter(guid=self.guid).first()
        else:
            return None

    @property
    def target(self):
        """Return the target of the abuse report (Addon, UserProfile...).
        Can return None if it could not be found."""
        if self.user_id:
            return self.user
        elif self.rating_id:
            return self.rating
        elif self.collection_id:
            return self.collection
        else:
            return self.addon

    @property
    def is_individually_actionable(self):
        """Is this abuse report reportable under DSA, so should be sent to Cinder"""
        return AbuseReport.objects.filter(
            AbuseReportManager.is_individually_actionable_q(), id=self.id
        ).exists()

    @property
    def is_handled_by_reviewers(self):
        return (
            (target := self.target)
            and isinstance(target, Addon)
            and self.reason in AbuseReport.REASONS.REVIEWER_HANDLED
            and self.location in AbuseReport.LOCATION.REVIEWER_HANDLED
        )

    @property
    def illegal_category_cinder_value(self):
        if not self.illegal_category:
            return None
        # We should send "normalized" constants to Cinder.
        const = ILLEGAL_CATEGORIES.for_value(self.illegal_category).constant
        return f'STATEMENT_CATEGORY_{const}'

    @property
    def illegal_subcategory_cinder_value(self):
        if not self.illegal_subcategory:
            return None
        # We should send "normalized" constants to Cinder.
        const = ILLEGAL_SUBCATEGORIES.for_value(self.illegal_subcategory).constant
        return f'KEYWORD_{const}'


class CantBeAppealed(Exception):
    pass


class CinderPolicyQuerySet(models.QuerySet):
    def without_parents_if_their_children_are_present(self):
        """Evaluates the queryset into a list, excluding parents of any child
        policy if present.
        """
        parents_ids = set(
            self.filter(parent__isnull=False).values_list('parent', flat=True)
        )
        return list(self.exclude(pk__in=parents_ids))


class CinderPolicy(ModelBase):
    uuid = models.CharField(max_length=36, unique=True)
    name = models.CharField(max_length=255)
    text = models.TextField()
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='children',
    )
    expose_in_reviewer_tools = models.BooleanField(default=False)
    default_cinder_action = models.PositiveSmallIntegerField(
        choices=DECISION_ACTIONS.choices, null=True, blank=True
    )
    present_in_cinder = models.BooleanField(null=True)

    objects = CinderPolicyQuerySet.as_manager()

    def __str__(self):
        return self.full_text('')

    def full_text(self, canned_response_text=None):
        if canned_response_text is None:
            canned_response_text = self.text
        parts = []
        if self.parent:
            parts.append(f'{self.parent.name}, specifically ')
        parts.append(self.name)
        if canned_response_text:
            parts.append(f': {canned_response_text}')
        return ''.join(parts)

    class Meta:
        verbose_name_plural = 'Cinder Policies'


class ContentDecision(ModelBase):
    action = models.PositiveSmallIntegerField(choices=DECISION_ACTIONS.choices)
    cinder_id = models.CharField(max_length=36, default=None, null=True, unique=True)
    action_date = models.DateTimeField(null=True, db_column='date')
    notes = models.TextField(max_length=1000, blank=True)
    policies = models.ManyToManyField(to='abuse.CinderPolicy')
    appeal_job = models.ForeignKey(
        to='abuse.CinderJob',
        null=True,
        on_delete=models.deletion.CASCADE,
        # Cinder also consolidates appeal jobs, so a single appeal can be an
        # appeal for multiple previous decisions (jobs).
        related_name='appealed_decisions',
    )
    override_of = models.OneToOneField(
        to='self',
        null=True,
        on_delete=models.SET_NULL,
        related_name='overridden_by',
    )
    reviewer_user = models.ForeignKey(
        UserProfile,
        null=True,
        on_delete=models.SET_NULL,
        related_name='decisions_made_by',
    )
    addon = models.ForeignKey(
        to=Addon,
        null=True,
        on_delete=models.deletion.SET_NULL,
        related_name='decisions_on',
    )
    target_versions = models.ManyToManyField(to=Version)
    user = models.ForeignKey(
        UserProfile, null=True, on_delete=models.SET_NULL, related_name='decisions_on'
    )
    rating = models.ForeignKey(
        Rating, null=True, on_delete=models.SET_NULL, related_name='decisions_on'
    )
    collection = models.ForeignKey(
        Collection, null=True, on_delete=models.SET_NULL, related_name='decisions_on'
    )
    activities = models.ManyToManyField(
        to='activity.ActivityLog', through='activity.ContentDecisionLog'
    )

    class Meta:
        db_table = 'abuse_cinderdecision'
        constraints = [
            models.CheckConstraint(
                name='just_one_of_addon_user_rating_collection_must_be_set',
                # Decision is against...
                # an addon
                check=models.Q(
                    addon__isnull=False,
                    user__isnull=True,
                    rating__isnull=True,
                    collection__isnull=True,
                )
                # or a user
                | models.Q(
                    addon__isnull=True,
                    user__isnull=False,
                    rating__isnull=True,
                    collection__isnull=True,
                )
                # or a rating
                | models.Q(
                    addon__isnull=True,
                    user__isnull=True,
                    rating__isnull=False,
                    collection__isnull=True,
                )
                # or a collection
                | models.Q(
                    addon__isnull=True,
                    user__isnull=True,
                    rating__isnull=True,
                    collection__isnull=False,
                ),
            ),
        ]

    @property
    def originating_job(self):
        return (
            self.override_of.originating_job
            if self.override_of
            else getattr(self, 'cinder_job', None)
        )

    def get_reference_id(self, short=True):
        if short and self.cinder_id:
            return self.cinder_id

        target = self.target
        target_class = target.__class__.__name__ if target else 'NoClass'
        fk_id = getattr(target, 'id', 'None')
        return (
            f'{target_class}#{fk_id}'
            if short
            else f'Decision "{self.cinder_id or ""}" for {target_class} #{fk_id}'
        )

    def __str__(self):
        return self.get_reference_id(short=False)

    @property
    def target(self):
        """Return the target of the decision (Addon, UserProfile...)."""
        if self.addon_id:
            return self.addon
        elif self.user_id:
            return self.user
        elif self.rating_id:
            return self.rating
        else:
            return self.collection

    def get_target_display(self):
        if self.addon_id:
            return self.addon.get_type_display()
        elif self.user_id:
            return _('User profile')
        else:
            return self.target.__class__.__name__

    @property
    def is_third_party_initiated(self):
        return bool((job := self.originating_job) and job.all_abuse_reports)

    @classmethod
    def get_action_helper_class(cls, decision_action):
        return {
            DECISION_ACTIONS.AMO_BAN_USER: ContentActionBanUser,
            DECISION_ACTIONS.AMO_DISABLE_ADDON: ContentActionDisableAddon,
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON: ContentActionRejectVersion,
            DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON: (
                ContentActionRejectVersionDelayed
            ),
            DECISION_ACTIONS.AMO_ESCALATE_ADDON: ContentActionForwardToReviewers,
            DECISION_ACTIONS.AMO_DELETE_COLLECTION: ContentActionDeleteCollection,
            DECISION_ACTIONS.AMO_DELETE_RATING: ContentActionDeleteRating,
            DECISION_ACTIONS.AMO_APPROVE: ContentActionApproveNoAction,
            DECISION_ACTIONS.AMO_APPROVE_VERSION: ContentActionApproveInitialDecision,
            DECISION_ACTIONS.AMO_IGNORE: ContentActionIgnore,
            DECISION_ACTIONS.AMO_CLOSED_NO_ACTION: ContentActionAlreadyRemoved,
            DECISION_ACTIONS.AMO_LEGAL_FORWARD: ContentActionForwardToLegal,
        }.get(decision_action, ContentActionNotImplemented)

    def get_action_helper(self):
        # Base case when it's a new decision, that wasn't an appeal
        ContentActionClass = self.get_action_helper_class(self.action)
        skip_reporter_notify = False
        any_cinder_job = self.originating_job
        overridden_action = (
            self.override_of
            and self.override_of.action_date
            and self.override_of.action
        )
        appealed_action = (
            getattr(any_cinder_job.appealed_decisions.first(), 'action', None)
            if any_cinder_job
            else None
        )

        if appealed_action:
            # target appeal
            if appealed_action in DECISION_ACTIONS.REMOVING:
                if self.action in DECISION_ACTIONS.NON_OFFENDING:
                    # i.e. we've reversed our target takedown
                    ContentActionClass = ContentActionTargetAppealApprove
                elif self.action == appealed_action:
                    # i.e. we've not reversed our target takedown
                    ContentActionClass = ContentActionTargetAppealRemovalAffirmation
            # (a reporter appeal doesn't need any alternate ContentAction class)

        elif overridden_action in DECISION_ACTIONS.REMOVING:
            # override on a decision that was a takedown before, and wasn't an appeal
            if self.action in DECISION_ACTIONS.NON_OFFENDING:
                ContentActionClass = ContentActionOverrideApprove
            if self.action == overridden_action:
                # For an override that is still a takedown we can send the same emails
                # to the target; but we don't want to notify the reporter again.
                skip_reporter_notify = True

        cinder_action = ContentActionClass(decision=self)
        if skip_reporter_notify:
            cinder_action.reporter_template_path = None
            cinder_action.reporter_appeal_template_path = None
        return cinder_action

    def can_be_appealed(self, *, is_reporter, abuse_report=None):
        """
        Whether or not the decision can be appealed.
        """
        now = datetime.now()
        base_criteria = (
            self.action_date
            and self.action_date >= now - timedelta(days=APPEAL_EXPIRATION_DAYS)
            # Can never appeal an original decision that has been appealed and
            # for which we already have a new decision. In some cases the
            # appealed decision (new decision id) can be appealed by the author
            # though (see below).
            and not self.appealed_decision_already_made()
            # if a decision has been overriden, the appeal must be on the overide
            and not hasattr(self, 'overridden_by')
        )
        user_criteria = (
            # Reporters can appeal decisions if they have a report and that
            # report has no appeals yet (the decision itself might already be
            # appealed - it can have multiple reporters). Note that we're only
            # attaching the abuse report to the original job, not the appeal,
            # by design.
            (
                is_reporter
                and abuse_report
                and self.is_third_party_initiated
                and abuse_report.cinder_job == self.originating_job
                and not hasattr(abuse_report, 'cinderappeal')
                and self.action in DECISION_ACTIONS.APPEALABLE_BY_REPORTER
            )
            or
            # Authors can appeal decisions not already appealed. Note that the
            # decision they are appealing might be a new decision following
            # an appeal from a reporter who disagreed with our initial decision
            # to keep the content up (always leaving a chance for the author
            # to be notified and appeal a decision against them, even if they
            # were not notified of an initial decision favorable to them).
            (
                not is_reporter
                and not self.appeal_job
                and self.action in DECISION_ACTIONS.APPEALABLE_BY_AUTHOR
            )
        )
        return base_criteria and user_criteria

    def appealed_decision_already_made(self):
        """
        Whether or not an appeal was already made for this decision.
        """
        return bool(
            self.appeal_job_id
            and self.appeal_job.decision_id
            and self.appeal_job.decision.cinder_id
        )

    @property
    def is_delayed(self):
        return self.action == DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON

    def appeal(self, *, abuse_report, appeal_text, user, is_reporter):
        appealer_entity = None
        if is_reporter:
            if not abuse_report:
                raise ImproperlyConfigured(
                    'ContentDecision.appeal() called with is_reporter=True without an '
                    'abuse_report'
                )
            if not user:
                appealer_entity = CinderJob.get_cinder_reporter(abuse_report)
        else:
            # If the appealer is not an original reporter, we have to provide
            # an authenticated user that is the author of the content.
            # User bans are a special case, since the user can't log in any
            # more at the time of the appeal, so we let that through using the
            # target of the job that banned them.
            if not user and self.action == DECISION_ACTIONS.AMO_BAN_USER:
                user = self.target
            if not isinstance(user, UserProfile):
                # If we still don't have a user at this point there is nothing
                # we can do, something was wrong in the call chain.
                raise ImproperlyConfigured(
                    'ContentDecision.appeal() called with is_reporter=False without '
                    'user'
                )
        if user:
            appealer_entity = CinderUser(user)

        resolvable_in_reviewer_tools = (
            not (job := self.originating_job) or job.resolvable_in_reviewer_tools
        )
        if not self.can_be_appealed(is_reporter=is_reporter, abuse_report=abuse_report):
            raise CantBeAppealed

        entity_helper = CinderJob.get_entity_helper(
            self.target,
            resolved_in_reviewer_tools=resolvable_in_reviewer_tools,
            addon_version_string=getattr(abuse_report, 'addon_version', None),
        )
        appeal_id = entity_helper.appeal(
            decision_cinder_id=self.cinder_id,
            appeal_text=appeal_text,
            appealer=appealer_entity,
        )
        with atomic():
            appeal_job, _ = CinderJob.objects.get_or_create(
                job_id=appeal_id,
                defaults={
                    'target_addon': self.addon,
                    'resolvable_in_reviewer_tools': resolvable_in_reviewer_tools,
                },
            )
            self.update(appeal_job=appeal_job)
            CinderAppeal.objects.create(
                text=appeal_text,
                decision=self,
                **({'reporter_report': abuse_report} if is_reporter else {}),
            )

    def report_to_cinder(self, entity_helper):
        """Report the decision to Cinder if:
        - not already reported, and
        - has an associated Job in Cinder, or not an action we skip reporting for.
        """
        if self.cinder_id:
            # We don't need to report the decision if it's already been reported
            return

        any_cinder_job = self.originating_job
        if self.action not in DECISION_ACTIONS.SKIP_DECISION or any_cinder_job:
            # we don't create cinder decisions for approvals that aren't resolving a job
            create_decision_kw = {
                'action': DECISION_ACTIONS.for_value(self.action).api_value,
                'reasoning': self.notes,
                'policy_uuids': list(self.policies.values_list('uuid', flat=True)),
            }
            if current_cinder_job := getattr(self, 'cinder_job', None):
                decision_cinder_id = entity_helper.create_job_decision(
                    job_id=current_cinder_job.job_id, **create_decision_kw
                )
            else:
                decision_cinder_id = entity_helper.create_decision(**create_decision_kw)
            self.update(cinder_id=decision_cinder_id)

    def execute_action(self, *, release_hold=False):
        """Execute the action for the decision, if not already carried out.
        The action may be held for 2nd level approval.
        If the action has been carried out, notify interested parties"""
        action_helper = self.get_action_helper()
        log_entry = None
        if not self.action_date:
            if release_hold or not action_helper.should_hold_action():
                # We set the action_date because .can_be_appealed depends on it
                self.action_date = datetime.now()
                log_entry = action_helper.process_action()
                # But only save it afterwards in case process_action failed
                self.save(update_fields=('action_date',))
            else:
                log_entry = action_helper.hold_action()

        log_entry = log_entry or self.activities.first()

        if self.action_date and (cinder_job := self.originating_job) and self.addon_id:
            if self.is_delayed:
                cinder_job.pending_rejections.add(
                    *VersionReviewerFlags.objects.filter(
                        version__in=log_entry.versionlog_set.values_list(
                            'version', flat=True
                        )
                    )
                )
            else:
                cinder_job.pending_rejections.clear()
            cinder_job.clear_needs_human_review_flags()
        return log_entry

    def send_notifications(self):
        if not self.action_date:
            return

        action_helper = self.get_action_helper()
        cinder_job = self.originating_job
        log_entry = self.activities.last()

        if cinder_job:
            cinder_job.notify_reporters(action_helper)

        if self.addon_id:
            details = (log_entry and log_entry.details) or {}
            # Using 'reviewtype' is a bit of a hack to allow us to differentiate
            # decisions from the reviewer tools, because it's only set there.
            from_reviewer_tools = 'reviewtype' in details
            is_auto_approval = (
                self.action == DECISION_ACTIONS.AMO_APPROVE_VERSION
                and not details.get('human_review', True)
            )
            version_numbers = (
                log_entry.versionlog_set.values_list('version__version', flat=True)
                if log_entry
                else []
            )
            extra_context = {
                'auto_approval': is_auto_approval,
                'delayed_rejection_days': details.get('delayed_rejection_days'),
                'is_addon_being_blocked': details.get('is_addon_being_blocked'),
                'is_addon_disabled': details.get('is_addon_being_disabled')
                or getattr(self.target, 'is_disabled', False),
                'version_list': ', '.join(ver_str for ver_str in version_numbers),
                'has_attachment': hasattr(log_entry, 'attachmentlog'),
                'dev_url': absolutify(self.target.get_dev_url('versions'))
                if self.addon_id
                else None,
                # Because we expand the reason/policy text into notes in the
                # reviewer tools, we don't want to duplicate it as policies too.
                **({'policies': ()} if self.notes and from_reviewer_tools else {}),
            }
        else:
            extra_context = {}

        action_helper.notify_owners(
            log_entry_id=getattr(log_entry, 'id', None), extra_context=extra_context
        )

    def get_target_review_url(self):
        return reverse('reviewers.decision_review', kwargs={'decision_id': self.id})

    def get_target_name(self):
        return str(
            _('"{}" for {}').format(self.rating, self.rating.addon.name)
            if self.rating
            else getattr(self.target, 'name', self.target)
        )


class CinderAppeal(ModelBase):
    text = models.TextField(blank=False, help_text='The content of the appeal.')
    decision = models.ForeignKey(
        to=ContentDecision, on_delete=models.CASCADE, related_name='appeals'
    )
    reporter_report = models.OneToOneField(
        to=AbuseReport, on_delete=models.CASCADE, null=True
    )


class CinderQueueMove(ModelBase):
    cinder_job = models.ForeignKey(
        to=CinderJob, on_delete=models.CASCADE, related_name='queue_moves'
    )
    notes = models.TextField(max_length=1000, blank=True)
    to_queue = models.CharField(max_length=128)
