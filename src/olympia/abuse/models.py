from datetime import datetime, timedelta
from itertools import chain

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.transaction import atomic
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property

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
)
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile
from olympia.versions.models import VersionReviewerFlags

from .cinder import (
    CinderAddon,
    CinderAddonHandledByReviewers,
    CinderCollection,
    CinderRating,
    CinderReport,
    CinderUnauthenticatedReporter,
    CinderUser,
)
from .utils import (
    CinderActionApproveInitialDecision,
    CinderActionApproveNoAction,
    CinderActionBanUser,
    CinderActionDeleteCollection,
    CinderActionDeleteRating,
    CinderActionDisableAddon,
    CinderActionEscalateAddon,
    CinderActionIgnore,
    CinderActionNotImplemented,
    CinderActionOverrideApprove,
    CinderActionRejectVersion,
    CinderActionRejectVersionDelayed,
    CinderActionTargetAppealApprove,
    CinderActionTargetAppealRemovalAffirmation,
)


class CinderJobQuerySet(BaseQuerySet):
    def for_addon(self, addon):
        return self.filter(target_addon=addon).order_by('-pk')

    def unresolved(self):
        return self.filter(
            models.Q(decision__isnull=True)
            | models.Q(decision__action__in=tuple(DECISION_ACTIONS.UNRESOLVED.values))
        )

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
        to='abuse.CinderDecision',
        null=True,
        on_delete=models.SET_NULL,
        related_name='cinder_job',
    )
    resolvable_in_reviewer_tools = models.BooleanField(default=None, null=True)

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
    def all_abuse_reports(self):
        return [
            *chain.from_iterable(
                decision.cinder_job.all_abuse_reports
                for decision in self.appealed_decisions.filter(cinder_job__isnull=False)
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
            version = (
                addon_version_string
                and target.versions(manager='unfiltered_for_relations')
                .filter(version=addon_version_string)
                .no_transforms()
                .first()
            )
            if resolved_in_reviewer_tools:
                return CinderAddonHandledByReviewers(target, version)
            else:
                return CinderAddon(target, version)
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
    def report(cls, abuse_report):
        report_entity = CinderReport(abuse_report)
        reporter_entity = cls.get_cinder_reporter(abuse_report)
        entity_helper = cls.get_entity_helper(
            abuse_report.target,
            addon_version_string=abuse_report.addon_version,
            resolved_in_reviewer_tools=abuse_report.is_handled_by_reviewers,
        )
        job_id = entity_helper.report(report=report_entity, reporter=reporter_entity)
        target = abuse_report.target
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

    def notify_reporters(self, action_helper):
        action_helper.notify_reporters(
            reporter_abuse_reports=self.abusereport_set.all(),
            is_appeal=False,
        )
        action_helper.notify_reporters(
            reporter_abuse_reports=self.appellants.all(),
            is_appeal=True,
        )

    def process_decision(
        self,
        *,
        decision_cinder_id,
        decision_date,
        decision_action,
        decision_notes,
        policy_ids,
    ):
        """This is called for cinder originated decisions.
        See resolve_job for reviewer tools originated decisions."""
        overriden_action = getattr(self.decision, 'action', None)
        # We need either an AbuseReport or CinderDecision for the target props
        abuse_report_or_decision = (
            self.appealed_decisions.first() or self.abusereport_set.first()
        )
        cinder_decision, _ = CinderDecision.objects.update_or_create(
            cinder_job=self,
            defaults={
                'addon': (
                    self.target_addon
                    if self.target_addon_id
                    else abuse_report_or_decision.addon
                ),
                'rating': abuse_report_or_decision.rating,
                'collection': abuse_report_or_decision.collection,
                'user': abuse_report_or_decision.user,
                'date': decision_date,
                'cinder_id': decision_cinder_id,
                'action': decision_action,
                'notes': decision_notes[
                    : CinderDecision._meta.get_field('notes').max_length
                ],
            },
        )
        self.update(
            decision=cinder_decision,
            resolvable_in_reviewer_tools=self.resolvable_in_reviewer_tools
            or decision_action == DECISION_ACTIONS.AMO_ESCALATE_ADDON,
        )
        policies = CinderPolicy.objects.filter(
            uuid__in=policy_ids
        ).without_parents_if_their_children_are_present()
        self.decision.policies.add(*policies)
        action_helper = self.decision.get_action_helper(
            overriden_action=overriden_action,
            appealed_action=getattr(self.appealed_decisions.first(), 'action', None),
        )
        log_entry = action_helper.process_action()
        self.notify_reporters(action_helper)
        action_helper.notify_owners(log_entry_id=getattr(log_entry, 'id', None))

    def resolve_job(self, *, log_entry):
        """This is called for reviewer tools originated decisions.
        See process_decision for cinder originated decisions."""
        from olympia.reviewers.models import NeedsHumanReview

        abuse_report_or_decision = (
            self.appealed_decisions.first() or self.abusereport_set.first()
        )
        if isinstance(abuse_report_or_decision, AbuseReport) and self.target_addon_id:
            # set the cached_property of AbuseReport.addon
            abuse_report_or_decision.addon = self.target_addon
        entity_helper = self.get_entity_helper(
            abuse_report_or_decision.target,
            resolved_in_reviewer_tools=self.resolvable_in_reviewer_tools,
        )
        was_escalated = (
            self.decision
            and self.decision.action == DECISION_ACTIONS.AMO_ESCALATE_ADDON
        )

        cinder_decision = self.decision or CinderDecision(
            addon=abuse_report_or_decision.addon,
            rating=abuse_report_or_decision.rating,
            collection=abuse_report_or_decision.collection,
            user=abuse_report_or_decision.user,
        )
        cinder_decision.cinder_job = self
        cinder_decision.notify_reviewer_decision(
            log_entry=log_entry,
            entity_helper=entity_helper,
            appealed_action=getattr(self.appealed_decisions.first(), 'action', None),
        )
        self.update(decision=cinder_decision)
        if self.decision.is_delayed:
            version_list = log_entry.versionlog_set.values_list('version', flat=True)
            self.pending_rejections.add(
                *VersionReviewerFlags.objects.filter(version__in=version_list)
            )
        else:
            self.pending_rejections.clear()
        if cinder_decision.addon_id:
            if was_escalated:
                reasons = [NeedsHumanReview.REASONS.CINDER_ESCALATION]
            else:
                reasons = (
                    [NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL]
                    if self.is_appeal
                    else []
                )
                if self.abusereport_set.exists():
                    reasons.append(NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION)
            NeedsHumanReview.objects.filter(
                version__addon_id=cinder_decision.addon_id,
                is_active=True,
                reason__in=reasons,
            ).update(is_active=False)
            cinder_decision.addon.update_all_due_dates()


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
        'REPORTABLE_REASONS',
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
    reporter_appeal_date = models.DateTimeField(default=None, null=True)
    appellant_job = models.ForeignKey(
        CinderJob,
        null=True,
        on_delete=models.SET_NULL,
        related_name='appellants',
    )
    illegal_category = models.PositiveSmallIntegerField(
        default=None,
        choices=ILLEGAL_CATEGORIES.choices,
        blank=True,
        null=True,
        help_text='Type of illegal content',
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


class CinderDecision(ModelBase):
    action = models.PositiveSmallIntegerField(choices=DECISION_ACTIONS.choices)
    cinder_id = models.CharField(max_length=36, default=None, null=True, unique=True)
    date = models.DateTimeField(default=timezone.now)
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
    addon = models.ForeignKey(to=Addon, null=True, on_delete=models.deletion.SET_NULL)
    user = models.ForeignKey(UserProfile, null=True, on_delete=models.SET_NULL)
    rating = models.ForeignKey(Rating, null=True, on_delete=models.SET_NULL)
    collection = models.ForeignKey(Collection, null=True, on_delete=models.SET_NULL)

    class Meta:
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

    @property
    def is_third_party_initiated(self):
        return hasattr(self, 'cinder_job') and bool(self.cinder_job.all_abuse_reports)

    @classmethod
    def get_action_helper_class(cls, decision_action):
        return {
            DECISION_ACTIONS.AMO_BAN_USER: CinderActionBanUser,
            DECISION_ACTIONS.AMO_DISABLE_ADDON: CinderActionDisableAddon,
            DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON: CinderActionRejectVersion,
            DECISION_ACTIONS.AMO_REJECT_VERSION_WARNING_ADDON: (
                CinderActionRejectVersionDelayed
            ),
            DECISION_ACTIONS.AMO_ESCALATE_ADDON: CinderActionEscalateAddon,
            DECISION_ACTIONS.AMO_DELETE_COLLECTION: CinderActionDeleteCollection,
            DECISION_ACTIONS.AMO_DELETE_RATING: CinderActionDeleteRating,
            DECISION_ACTIONS.AMO_APPROVE: CinderActionApproveNoAction,
            DECISION_ACTIONS.AMO_APPROVE_VERSION: CinderActionApproveInitialDecision,
            DECISION_ACTIONS.AMO_IGNORE: CinderActionIgnore,
        }.get(decision_action, CinderActionNotImplemented)

    def get_action_helper(self, *, overriden_action=None, appealed_action=None):
        # Base case when it's a new decision, that wasn't an appeal
        CinderActionClass = self.get_action_helper_class(self.action)
        skip_reporter_notify = False

        if appealed_action:
            # target appeal
            if appealed_action in DECISION_ACTIONS.REMOVING:
                if self.action in DECISION_ACTIONS.APPROVING:
                    # i.e. we've reversed our target takedown
                    CinderActionClass = CinderActionTargetAppealApprove
                elif self.action == appealed_action:
                    # i.e. we've not reversed our target takedown
                    CinderActionClass = CinderActionTargetAppealRemovalAffirmation
            # (a reporter appeal doesn't need any alternate CinderAction class)

        elif overriden_action in DECISION_ACTIONS.REMOVING:
            # override on a decision that was a takedown before, and wasn't an appeal
            if self.action in DECISION_ACTIONS.APPROVING:
                CinderActionClass = CinderActionOverrideApprove
            if self.action == overriden_action:
                # For an override that is still a takedown we can send the same emails
                # to the target; but we don't want to notify the reporter again.
                skip_reporter_notify = True

        cinder_action = CinderActionClass(decision=self)
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
            self.date
            and self.date >= now - timedelta(days=APPEAL_EXPIRATION_DAYS)
            # Can never appeal an original decision that has been appealed and
            # for which we already have a new decision. In some cases the
            # appealed decision (new decision id) can be appealed by the author
            # though (see below).
            and not self.appealed_decision_already_made()
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
                and abuse_report.cinder_job == self.cinder_job
                and not abuse_report.appellant_job
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
                    'CinderDecision.appeal() called with is_reporter=True without an '
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
                    'CinderDecision.appeal() called with is_reporter=False without user'
                )
        if user:
            appealer_entity = CinderUser(user)

        resolvable_in_reviewer_tools = (
            not hasattr(self, 'cinder_job')
            or self.cinder_job.resolvable_in_reviewer_tools
        )
        if not self.can_be_appealed(is_reporter=is_reporter, abuse_report=abuse_report):
            raise CantBeAppealed

        entity_helper = CinderJob.get_entity_helper(
            self.target, resolved_in_reviewer_tools=resolvable_in_reviewer_tools
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
            if is_reporter:
                abuse_report.update(
                    reporter_appeal_date=datetime.now(), appellant_job=appeal_job
                )

    def notify_reviewer_decision(
        self,
        *,
        log_entry,
        entity_helper,
        appealed_action=None,
    ):
        """Calling this method calls cinder to create a decision, or notfies the content
        owner/reporter by email, or both.

        If a decision is created in cinder the instance will be saved, along with
        relevant policies; if a cinder decision isn't need the instance won't be saved.
        """
        if not DECISION_ACTIONS.has_constant(
            log_entry.details.get('cinder_action', '')
        ):
            raise ImproperlyConfigured(
                'Missing or invalid cinder_action in activity log details passed to '
                'notify_reviewer_decision'
            )
        overriden_action = self.action
        self.action = DECISION_ACTIONS.for_constant(
            log_entry.details['cinder_action']
        ).value

        if self.action not in DECISION_ACTIONS.APPROVING or hasattr(self, 'cinder_job'):
            # we don't create cinder decisions for approvals that aren't resolving a job
            policies = {
                cpl.cinder_policy for cpl in log_entry.cinderpolicylog_set.all()
            }
            create_decision_kw = {
                'action': self.action.api_value,
                'reasoning': log_entry.details.get('comments', ''),
                'policy_uuids': [policy.uuid for policy in policies],
            }
            if cinder_job := getattr(self, 'cinder_job', None):
                decision_cinder_id = entity_helper.create_job_decision(
                    job_id=cinder_job.job_id, **create_decision_kw
                )
            else:
                decision_cinder_id = entity_helper.create_decision(**create_decision_kw)
            with atomic():
                self.cinder_id = decision_cinder_id
                self.save()
                self.policies.set(policies)

        action_helper = self.get_action_helper(
            overriden_action=overriden_action, appealed_action=appealed_action
        )
        if cinder_job := getattr(self, 'cinder_job', None):
            cinder_job.notify_reporters(action_helper)
        versions_data = log_entry.versionlog_set.values_list(
            'version__version', 'version__channel'
        )
        # override target_url if this decision related to unlisted versions
        target_url_override = (
            {
                'target_url': absolutify(
                    reverse('devhub.addons.versions', args=[self.target.id])
                )
            }
            if versions_data and versions_data[0][1] == amo.CHANNEL_UNLISTED
            else {}
        )
        is_auto_approval = (
            self.action in DECISION_ACTIONS.APPROVING
            and not log_entry.details.get('human_review', True)
        )
        action_helper.notify_owners(
            log_entry_id=log_entry.id,
            policy_text=log_entry.details.get('comments'),
            extra_context={
                'auto_approval': is_auto_approval,
                'delayed_rejection_days': log_entry.details.get(
                    'delayed_rejection_days'
                ),
                'is_addon_being_blocked': log_entry.details.get(
                    'is_addon_being_blocked'
                ),
                'is_addon_disabled': log_entry.details.get('is_addon_being_disabled')
                or self.target.is_disabled,
                'version_list': ', '.join(ver_str for ver_str, _ in versions_data),
                **target_url_override,
            },
        )
