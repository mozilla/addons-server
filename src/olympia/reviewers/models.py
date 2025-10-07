import json
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.db.models import Avg, Count, OuterRef, Q
from django.db.models.functions import Greatest
from django.dispatch import receiver
from django.template import loader
from django.urls import reverse
from django.utils.functional import cached_property

from extended_choices import Choices
from extended_choices.helpers import ChoiceEntry

import olympia.core.logger
from olympia import activity, amo, core
from olympia.abuse.models import AbuseReport, CinderPolicy
from olympia.access import acl
from olympia.addons.models import Addon, AddonApprovalsCounter
from olympia.amo.models import ModelBase
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import send_mail
from olympia.files.models import File, FileValidation
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile
from olympia.users.utils import get_task_user
from olympia.versions.models import Version, version_uploaded
from olympia.versions.utils import get_staggered_review_due_date_generator
from olympia.zadmin.models import get_config


user_log = olympia.core.logger.getLogger('z.users')

log = olympia.core.logger.getLogger('z.reviewers')


VIEW_QUEUE_FLAGS = (
    (
        'needs_admin_theme_review',
        'Needs Admin Static Theme Review',
    ),
    (
        'sources_provided',
        'Source Code Provided',
    ),
    (
        'auto_approval_disabled',
        'Auto-approval disabled',
    ),
    (
        'auto_approval_delayed_temporarily',
        'Auto-approval delayed temporarily',
    ),
    (
        'auto_approval_delayed_indefinitely',
        'Auto-approval delayed indefinitely',
    ),
    (
        'auto_approval_disabled_unlisted',
        'Unlisted Auto-approval disabled',
    ),
    (
        'auto_approval_delayed_temporarily_unlisted',
        'Unlisted Auto-approval delayed temporarily',
    ),
    (
        'auto_approval_delayed_indefinitely_unlisted',
        'Unlisted Auto-approval delayed indefinitely',
    ),
)


def get_reviewing_cache_key(addon_id):
    return f'review_viewing:{addon_id}'


def clear_reviewing_cache(addon_id):
    return cache.delete(get_reviewing_cache_key(addon_id))


def get_reviewing_cache(addon_id):
    return cache.get(get_reviewing_cache_key(addon_id))


def set_reviewing_cache(addon_id, user_id):
    # We want to save it for twice as long as the ping interval,
    # just to account for latency and the like.
    cache.set(
        get_reviewing_cache_key(addon_id), user_id, amo.REVIEWER_VIEWING_INTERVAL * 2
    )


def get_flags(addon, version):
    """Return a list of tuples (indicating which flags should be displayed for
    a particular add-on."""
    exclude_flags_by_channel = {
        amo.CHANNEL_UNLISTED: (
            'auto_approval_disabled',
            'auto_approval_delayed_temporarily',
            'auto_approval_delayed_indefinitely',
        ),
        amo.CHANNEL_LISTED: (
            'auto_approval_disabled_unlisted',
            'auto_approval_delayed_temporarily_unlisted',
            'auto_approval_delayed_indefinitely_unlisted',
        ),
    }
    flags = [
        (prop.replace('_', '-'), title)
        for (prop, title) in VIEW_QUEUE_FLAGS
        + tuple(
            (entry.annotation, entry.display)
            for entry in NeedsHumanReview.REASONS.entries
        )
        if getattr(version, prop, getattr(addon, prop, None))
        and prop
        not in exclude_flags_by_channel.get(getattr(version, 'channel', None), ())
    ]

    # add in the promoted group flag and return
    if promoted := addon.promoted_groups(currently_approved=False):
        for group in promoted:
            flags.append((f'promoted-{group.api_name}', group.name))
    return flags


class ReviewerSubscription(ModelBase):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    addon = models.ForeignKey(Addon, on_delete=models.CASCADE)
    channel = models.PositiveSmallIntegerField(choices=amo.CHANNEL_CHOICES.items())

    class Meta:
        db_table = 'editor_subscriptions'

    def send_notification(self, version):
        user_log.info(
            'Sending addon update notice to %s for %s'
            % (self.user.email, self.addon.pk)
        )

        if version.channel == amo.CHANNEL_LISTED:
            listing_url = absolutify(
                reverse('addons.detail', args=[self.addon.pk], add_prefix=False)
            )
        else:
            # If the submission went to the unlisted channel,
            # do not link to the listing.
            listing_url = None
        context = {
            'name': self.addon.name,
            'url': listing_url,
            'number': version.version,
            'review': absolutify(
                reverse(
                    'reviewers.review',
                    kwargs={
                        'addon_id': self.addon.pk,
                        'channel': amo.CHANNEL_CHOICES_API[version.channel],
                    },
                    add_prefix=False,
                )
            ),
            'SITE_URL': settings.SITE_URL,
        }
        # Not being localised because we don't know the reviewer's locale.
        subject = 'Mozilla Add-ons: %s Updated' % self.addon.name
        template = loader.get_template('reviewers/emails/notify_update.ltxt')
        send_mail(
            subject,
            template.render(context),
            recipient_list=[self.user.email],
            use_deny_list=False,
        )


def send_notifications(sender=None, instance=None, signal=None, **kw):
    subscribers = instance.addon.reviewersubscription_set.all()

    if not subscribers:
        return

    listed_perms = [
        amo.permissions.ADDONS_REVIEW,
        amo.permissions.ADDONS_CONTENT_REVIEW,
        amo.permissions.ADDONS_RECOMMENDED_REVIEW,
        amo.permissions.STATIC_THEMES_REVIEW,
        amo.permissions.REVIEWER_TOOLS_VIEW,
    ]

    unlisted_perms = [
        amo.permissions.ADDONS_REVIEW_UNLISTED,
        amo.permissions.REVIEWER_TOOLS_UNLISTED_VIEW,
    ]

    for subscriber in subscribers:
        user = subscriber.user
        is_active_user = user and not user.deleted and user.email
        is_reviewer_and_listed_submission = (
            subscriber.channel == amo.CHANNEL_LISTED
            and instance.channel == amo.CHANNEL_LISTED
            and any(acl.action_allowed_for(user, perm) for perm in listed_perms)
        )
        is_unlisted_reviewer_and_unlisted_submission = (
            subscriber.channel == amo.CHANNEL_UNLISTED
            and instance.channel == amo.CHANNEL_UNLISTED
            and any(acl.action_allowed_for(user, perm) for perm in unlisted_perms)
        )
        if is_active_user and (
            is_reviewer_and_listed_submission
            or is_unlisted_reviewer_and_unlisted_submission
        ):
            subscriber.send_notification(instance)


version_uploaded.connect(send_notifications, dispatch_uid='send_notifications')


class AutoApprovalNoValidationResultError(Exception):
    pass


class AutoApprovalSummary(ModelBase):
    """Model holding the results of an auto-approval attempt on a Version."""

    version = models.OneToOneField(Version, on_delete=models.CASCADE, primary_key=True)
    is_locked = models.BooleanField(default=False, help_text='Is locked by a reviewer')
    has_auto_approval_disabled = models.BooleanField(
        default=False, help_text='Has auto-approval disabled/delayed flag set'
    )
    is_promoted_prereview = models.BooleanField(
        default=False,
        null=True,  # TODO: remove this once code has deployed to prod.
        help_text='Is in a promoted add-on group that requires pre-review',
    )
    should_be_delayed = models.BooleanField(
        default=False, help_text="Delayed because it's the first listed version"
    )
    is_blocked = models.BooleanField(
        default=False, help_text='Version string and guid match a blocklist Block'
    )
    is_pending_rejection = models.BooleanField(
        default=False, help_text='Is pending rejection'
    )
    verdict = models.PositiveSmallIntegerField(
        choices=amo.AUTO_APPROVAL_VERDICT_CHOICES, default=amo.NOT_AUTO_APPROVED
    )
    weight = models.IntegerField(default=0)
    metadata_weight = models.IntegerField(default=0)
    code_weight = models.IntegerField(default=0)
    weight_info = models.JSONField(default=dict, null=True)
    confirmed = models.BooleanField(null=True, default=None)

    class Meta:
        db_table = 'editors_autoapprovalsummary'

    # List of fields to check when determining whether a version should be
    # auto-approved or not. Each should be a boolean, a value of true means
    # the version will *not* auto-approved. Each should have a corresponding
    # check_<reason>(version) classmethod defined that will be used by
    # create_summary_for_version() to set the corresponding field on the
    # instance.
    auto_approval_verdict_fields = (
        'has_auto_approval_disabled',
        'is_locked',
        'is_promoted_prereview',
        'should_be_delayed',
        'is_blocked',
        'is_pending_rejection',
    )

    def __str__(self):
        return f'{self.version.addon.name} {self.version}'

    def calculate_weight(self):
        """Calculate the weight value for this version according to various
        risk factors, setting the weight (an integer) and weight_info (a dict
        of risk factors strings -> integer values) properties on the instance.

        The weight value is then used in reviewer tools to prioritize add-ons
        in the auto-approved queue, the weight_info shown to reviewers in the
        review page."""
        metadata_weight_factors = self.calculate_metadata_weight_factors()
        code_weight_factors = self.calculate_code_weight_factors()
        self.metadata_weight = sum(metadata_weight_factors.values())
        self.code_weight = sum(code_weight_factors.values())
        self.weight_info = {
            k: v
            for k, v in dict(**metadata_weight_factors, **code_weight_factors).items()
            # No need to keep 0 value items in the breakdown in the db, they won't be
            # displayed anyway.
            if v
        }
        self.weight = self.metadata_weight + self.code_weight
        return self.weight_info

    def calculate_metadata_weight_factors(self):
        addon = self.version.addon
        one_year_ago = (self.created or datetime.now()) - timedelta(days=365)
        six_weeks_ago = (self.created or datetime.now()) - timedelta(days=42)
        factors = {
            # Each abuse reports for the add-on or one of the listed developers
            # in the last 6 weeks adds 15 to the weight, up to a maximum of
            # 100.
            'abuse_reports': min(
                AbuseReport.objects.filter(
                    Q(guid=addon.guid) | Q(user__in=addon.listed_authors)
                )
                .filter(created__gte=six_weeks_ago)
                .count()
                * 15,
                100,
            ),
            # 1% of the total of "recent" ratings with a score of 3 or less
            # adds 2 to the weight, up to a maximum of 100.
            'negative_ratings': min(
                int(
                    Rating.objects.filter(addon=addon)
                    .filter(rating__lte=3, created__gte=one_year_ago)
                    .count()
                    / 100.0
                    * 2.0
                ),
                100,
            ),
            # Reputation is set by admin - the value is inverted to add from
            # -300 (decreasing priority for "trusted" add-ons) to 0.
            'reputation': (max(min(int(addon.reputation or 0) * -100, 0), -300)),
            # Average daily users: value divided by 10000 is added to the
            # weight, up to a maximum of 100.
            'average_daily_users': min(addon.average_daily_users // 10000, 100),
            # Past rejection history: each "recent" rejected version
            # adds 10 to the weight, up to a maximum of 100.
            'past_rejection_history': min(
                Version.objects.filter(
                    addon=addon,
                    human_review_date__gte=one_year_ago,
                    file__status_disabled_reason=File.STATUS_DISABLED_REASONS.NONE,
                    file__status=amo.STATUS_DISABLED,
                ).count()
                * 10,
                100,
            ),
        }
        return factors

    def calculate_code_weight_factors(self):
        """Calculate the static analysis risk factors, returning a dict of
        risk factors.

        Used by calculate_weight()."""
        try:
            innerhtml_count = self.count_uses_innerhtml(self.version)
            unknown_minified_code_count = self.count_uses_unknown_minified_code(
                self.version
            )

            factors = {
                # Static analysis flags from linter:
                # eval() or document.write(): 50.
                'uses_eval_or_document_write': (
                    50 if self.count_uses_eval_or_document_write(self.version) else 0
                ),
                # Implied eval in setTimeout/setInterval/ on* attributes: 5.
                'uses_implied_eval': (
                    5 if self.count_uses_implied_eval(self.version) else 0
                ),
                # innerHTML / unsafe DOM: 50+10 per instance.
                'uses_innerhtml': (
                    50 + 10 * (innerhtml_count - 1) if innerhtml_count else 0
                ),
                # custom CSP: 90.
                'uses_custom_csp': (
                    90 if self.count_uses_custom_csp(self.version) else 0
                ),
                # nativeMessaging permission: 100.
                'uses_native_messaging': (
                    100 if self.check_uses_native_messaging(self.version) else 0
                ),
                # remote scripts: 100.
                'uses_remote_scripts': (
                    100 if self.count_uses_remote_scripts(self.version) else 0
                ),
                # violates mozilla conditions of use: 20.
                'violates_mozilla_conditions': (
                    20 if self.count_violates_mozilla_conditions(self.version) else 0
                ),
                # libraries of unreadable code: 100+10 per instance.
                'uses_unknown_minified_code': (
                    100 + 10 * (unknown_minified_code_count - 1)
                    if unknown_minified_code_count
                    else 0
                ),
                # Size of code changes: 5kB is one point, up to a max of 100.
                'size_of_code_changes': min(
                    self.calculate_size_of_code_changes() // 5000, 100
                ),
                # Seems to be using a coinminer: 2000
                'uses_coinminer': (
                    2000 if self.count_uses_uses_coinminer(self.version) else 0
                ),
            }
        except AutoApprovalNoValidationResultError:
            # We should have a FileValidationResult... since we don't and
            # something is wrong, increase the weight by 500.
            factors = {
                'no_validation_result': 500,
            }
        return factors

    def get_pretty_weight_info(self):
        """Returns a list of strings containing weight information."""
        if self.weight_info:
            weight_info = sorted(
                '%s: %d' % (k, v) for k, v in self.weight_info.items() if v
            )
        else:
            weight_info = ['Weight breakdown not available.']
        return weight_info

    def find_previous_confirmed_version(self):
        """Return the most recent version in the add-on history that has been
        confirmed, excluding the one this summary is about, or None if there
        isn't one."""
        addon = self.version.addon
        try:
            version = (
                addon.versions.exclude(pk=self.version.pk)
                .filter(autoapprovalsummary__confirmed=True)
                .latest()
            )
        except Version.DoesNotExist:
            version = None
        return version

    def calculate_size_of_code_changes(self):
        """Return the size of code changes between the version being
        approved and the previous public one."""

        def find_code_size(version):
            data = json.loads(version.file.validation.validation)
            total_code_size = data.get('metadata', {}).get('totalScannedFileSize', 0)
            return total_code_size

        try:
            old_version = self.find_previous_confirmed_version()
            old_size = find_code_size(old_version) if old_version else 0
            new_size = find_code_size(self.version)
        except FileValidation.DoesNotExist as exc:
            raise AutoApprovalNoValidationResultError() from exc
        # We don't really care about whether it's a negative or positive change
        # in size, we just need the absolute value (if there is no current
        # public version, that value ends up being the total code size of the
        # version we're approving).
        return abs(old_size - new_size)

    def calculate_verdict(self, dry_run=False, pretty=False):
        """Calculate the verdict for this instance based on the values set
        on it previously and the current configuration.

        Return a dict containing more information about what critera passed
        or not."""
        if dry_run:
            success_verdict = amo.WOULD_HAVE_BEEN_AUTO_APPROVED
            failure_verdict = amo.WOULD_NOT_HAVE_BEEN_AUTO_APPROVED
        else:
            success_verdict = amo.AUTO_APPROVED
            failure_verdict = amo.NOT_AUTO_APPROVED

        verdict_info = {
            key: bool(getattr(self, key)) for key in self.auto_approval_verdict_fields
        }
        if any(verdict_info.values()):
            self.verdict = failure_verdict
        else:
            self.verdict = success_verdict

        if pretty:
            verdict_info = self.verdict_info_prettifier(verdict_info)

        return verdict_info

    @classmethod
    def verdict_info_prettifier(cls, verdict_info):
        """Return a generator of strings representing the a verdict_info
        (as computed by calculate_verdict()) in human-readable form."""
        return (
            str(cls._meta.get_field(key).help_text)
            for key, value in sorted(verdict_info.items())
            if value
        )

    @classmethod
    def _count_linter_flag(cls, version, flag):
        try:
            validation = version.file.validation
        except FileValidation.DoesNotExist as exc:
            raise AutoApprovalNoValidationResultError() from exc
        validation_data = json.loads(validation.validation)
        return sum(
            flag in message['id'] for message in validation_data.get('messages', [])
        )

    @classmethod
    def _count_metadata_property(cls, version, prop):
        try:
            validation = version.file.validation
        except FileValidation.DoesNotExist as exc:
            raise AutoApprovalNoValidationResultError() from exc
        validation_data = json.loads(validation.validation)
        return len(validation_data.get('metadata', {}).get(prop, []))

    @classmethod
    def count_uses_unknown_minified_code(cls, version):
        return cls._count_metadata_property(version, 'unknownMinifiedFiles')

    @classmethod
    def count_violates_mozilla_conditions(cls, version):
        return cls._count_linter_flag(version, 'MOZILLA_COND_OF_USE')

    @classmethod
    def count_uses_remote_scripts(cls, version):
        return cls._count_linter_flag(version, 'REMOTE_SCRIPT')

    @classmethod
    def count_uses_eval_or_document_write(cls, version):
        return cls._count_linter_flag(
            version, 'NO_DOCUMENT_WRITE'
        ) or cls._count_linter_flag(version, 'DANGEROUS_EVAL')

    @classmethod
    def count_uses_implied_eval(cls, version):
        return cls._count_linter_flag(version, 'NO_IMPLIED_EVAL')

    @classmethod
    def count_uses_innerhtml(cls, version):
        return cls._count_linter_flag(version, 'UNSAFE_VAR_ASSIGNMENT')

    @classmethod
    def count_uses_custom_csp(cls, version):
        return cls._count_linter_flag(version, 'MANIFEST_CSP')

    @classmethod
    def count_uses_uses_coinminer(cls, version):
        return cls._count_linter_flag(version, 'COINMINER_USAGE_DETECTED')

    @classmethod
    def check_uses_native_messaging(cls, version):
        return 'nativeMessaging' in version.file.permissions

    @classmethod
    def check_is_locked(cls, version):
        """Check whether the add-on is locked by a reviewer.

        Doesn't apply to langpacks, which are submitted as part of Firefox
        release process and should always be auto-approved."""
        is_langpack = version.addon.type == amo.ADDON_LPAPP
        locked_by = get_reviewing_cache(version.addon.pk)
        return (
            not is_langpack and bool(locked_by) and locked_by != settings.TASK_USER_ID
        )

    @classmethod
    def check_has_auto_approval_disabled(cls, version):
        """Check whether the add-on has auto approval disabled or delayed.

        It could be:
        - Disabled
        - Disabled until next manual approval
        - Delayed until a future date

        Those flags are set by scanners or reviewers for a specific channel.
        """
        addon = version.addon
        flag_suffix = '_unlisted' if version.channel == amo.CHANNEL_UNLISTED else ''
        auto_approval_disabled = bool(
            getattr(addon, f'auto_approval_disabled{flag_suffix}')
        )
        auto_approval_disabled_until_next_approval = bool(
            getattr(addon, f'auto_approval_disabled_until_next_approval{flag_suffix}')
        )
        auto_approval_delayed_until = getattr(
            addon, f'auto_approval_delayed_until{flag_suffix}'
        )
        return bool(
            auto_approval_disabled
            or auto_approval_disabled_until_next_approval
            or (
                auto_approval_delayed_until
                and datetime.now() < auto_approval_delayed_until
            )
        )

    @classmethod
    def check_is_promoted_prereview(cls, version):
        """Check whether the add-on is a promoted addon group that requires
        pre-review."""
        promotions = version.addon.promoted_groups(currently_approved=False)

        return bool(
            promotions.exists()
            and (
                (
                    version.channel == amo.CHANNEL_LISTED
                    and any(promotions.listed_pre_review)
                )
                or (
                    version.channel == amo.CHANNEL_UNLISTED
                    and any(promotions.unlisted_pre_review)
                )
            )
        )

    @classmethod
    def check_should_be_delayed(cls, version):
        """Check whether the add-on is new enough that the auto-approval of the
        version should be delayed for 24 hours to catch spam.

        Doesn't apply to langpacks, which are submitted as part of Firefox
        release process and should always be auto-approved.
        Only applies to listed versions.
        """
        addon = version.addon
        is_langpack = addon.type == amo.ADDON_LPAPP
        now = datetime.now()
        try:
            content_review = addon.addonapprovalscounter.last_content_review
        except AddonApprovalsCounter.DoesNotExist:
            content_review = None
        INITIAL_AUTO_APPROVAL_DELAY_FOR_LISTED = get_config(
            amo.config_keys.INITIAL_AUTO_APPROVAL_DELAY_FOR_LISTED
        )
        return (
            not is_langpack
            and version.channel == amo.CHANNEL_LISTED
            and version.addon.status == amo.STATUS_NOMINATED
            and now - version.created
            < timedelta(seconds=INITIAL_AUTO_APPROVAL_DELAY_FOR_LISTED)
            and content_review is None
        )

    @classmethod
    def check_is_blocked(cls, version):
        """Check if the version matches a Block in the blocklist.  Such uploads
        would have been prevented, but if it was uploaded before the Block was
        created, it's possible it'll still be pending."""
        return version.is_blocked

    @classmethod
    def check_is_pending_rejection(cls, version):
        """Check whether the version is pending rejection. We don't
        auto-approve those versions, since it would just be confusing as they
        are eventually going to be rejected automatically anyway."""
        return bool(version.pending_rejection)

    @classmethod
    def create_summary_for_version(cls, version, dry_run=False):
        """Create a AutoApprovalSummary instance in db from the specified
        version.

        Return a tuple with the AutoApprovalSummary instance as first item,
        and a dict containing information about the auto approval verdict as
        second item.

        If dry_run parameter is True, then the instance is created/updated
        normally but when storing the verdict the WOULD_ constants are used
        instead.

        If not using dry_run it's the caller responsability to approve the
        version to make sure the AutoApprovalSummary is not overwritten later
        when the auto-approval process fires again."""
        data = {
            field: getattr(cls, f'check_{field}')(version)
            for field in cls.auto_approval_verdict_fields
        }
        instance = cls(version=version, **data)
        verdict_info = instance.calculate_verdict(dry_run=dry_run)
        instance.calculate_weight()
        # We can't do instance.save(), because we want to handle the case where
        # it already existed. So we put the verdict and weight we just
        # calculated in data and use update_or_create().
        data['verdict'] = instance.verdict
        data['weight'] = instance.weight
        data['metadata_weight'] = instance.metadata_weight
        data['code_weight'] = instance.code_weight
        data['weight_info'] = instance.weight_info
        instance, _ = cls.objects.update_or_create(version=version, defaults=data)
        return instance, verdict_info


class Whiteboard(ModelBase):
    addon = models.OneToOneField(Addon, on_delete=models.CASCADE, primary_key=True)
    private = models.TextField(blank=True, max_length=100000)
    public = models.TextField(blank=True, max_length=100000)

    class Meta:
        db_table = 'review_whiteboard'

    def __str__(self):
        return '[{}] private: |{}| public: |{}|'.format(
            self.addon.name,
            self.private,
            self.public,
        )


class ReviewActionReason(ModelBase):
    is_active = models.BooleanField(
        default=True, help_text='Is available to be used in reviews'
    )
    name = models.CharField(max_length=255)
    canned_response = models.TextField(blank=True)
    canned_block_reason = models.TextField(blank=True)
    addon_type = models.PositiveIntegerField(
        choices=amo.REASON_ADDON_TYPE_CHOICES.items(),
        default=amo.ADDON_ANY,
    )
    cinder_policy = models.ForeignKey(
        CinderPolicy, blank=True, null=True, on_delete=models.SET_NULL
    )

    def labelled_name(self):
        return '(** inactive **) ' + self.name if not self.is_active else self.name

    class Meta:
        ordering = ('name',)
        constraints = [
            models.CheckConstraint(
                name='either_canned_response_or_canned_block_reason_must_be_set',
                check=(
                    ~models.Q(canned_response='') | ~models.Q(canned_block_reason='')
                ),
            )
        ]

    def __str__(self):
        return str(self.name)


class UsageTier(ModelBase):
    slug = models.CharField(
        max_length=255,
        help_text='Slug to help retrieve the UsageTier instance in our code.',
        unique=True,
        null=True,
    )
    name = models.CharField(max_length=255)
    lower_adu_threshold = models.IntegerField(default=None, null=True, blank=True)
    upper_adu_threshold = models.IntegerField(default=None, null=True, blank=True)
    growth_threshold_before_flagging = models.IntegerField(
        blank=True,
        default=None,
        null=True,
        help_text='Percentage point increase in growth over the average in that tier '
        'before we start automatically flagging the add-on for human review. For '
        'example, if set to 50 and the average hotness in that tier is 0.01, '
        'add-ons over 0.51 hotness get flagged.',
    )
    abuse_reports_ratio_threshold_before_flagging = models.IntegerField(
        blank=True,
        default=None,
        null=True,
        help_text='Percentage threshold of ratio between non individually actionable '
        'abuse reports over the past 2 weeks to add-on usage before we start '
        'automatically flagging the add-on for human review. For example, if set to 2 '
        'and an add-on in that tier has 10,000 users, it will be flagged after 200 '
        'reports.',
    )
    ratings_ratio_threshold_before_flagging = models.IntegerField(
        blank=True,
        default=None,
        null=True,
        help_text='Percentage threshold of ratio between ratings over the past 2 weeks'
        'to add-on usage before we start automatically flagging the add-on for human '
        'review. '
        'For example, if set to 5 and an add-on in that tier has 10,000 users, '
        'it will be flagged after 500 ratings.',
    )
    abuse_reports_ratio_threshold_before_blocking = models.IntegerField(
        blank=True,
        default=None,
        null=True,
        help_text='Percentage threshold of ratio between non individually actionable '
        'abuse reports over the past 2 weeks to add-on usage before we automatically '
        'disable and soft-block the add-on. '
        'For example, if set to 4 and an add-on in that tier has 10,000 users, it will '
        'be blocked after 400 reports.',
    )
    ratings_ratio_threshold_before_blocking = models.IntegerField(
        blank=True,
        default=None,
        null=True,
        help_text='Percentage threshold of ratio between ratings over the past 2 weeks'
        'to add-on usage before we automatically disable and soft-block the add-on. '
        'For example, if set to 5 and an add-on in that tier has 10,000 users, '
        'it will be blocked after 500 ratings.',
    )
    disable_and_block_action_available = models.BooleanField(
        default=False,
        help_text='Whether or not the "Force-disable and block" scanner action should'
        'be available for add-ons belonging to that usage tier.',
    )

    class Meta:
        ordering = ('upper_adu_threshold',)

    def __str__(self):
        return self.name

    @classmethod
    def get_base_addons(cls):
        """Return base queryset of add-ons we consider for functionality tied
        to Usage Tiers.

        This is a classmethod, it is not specific to a particular tier."""
        return Addon.unfiltered.exclude(status=amo.STATUS_DISABLED).filter(
            type=amo.ADDON_EXTENSION
        )

    def get_tier_boundaries(self):
        """Return boundaries used to filter add-ons for that tier instance."""
        # We always have a lower bound, but not necessarily a higher one, e.g.
        # notable doesn't have a ceiling.
        filters = {'average_daily_users__gte': self.lower_adu_threshold or 0}
        if self.upper_adu_threshold is not None:
            filters['average_daily_users__lt'] = self.upper_adu_threshold
        return filters

    def get_addons(self):
        """Return add-ons considered as being part of that specific tier.

        See get_base_addon() for additional filters being applied."""
        return self.get_base_addons().filter(**self.get_tier_boundaries())

    @cached_property
    def average_growth(self):
        return (
            self.get_addons()
            .aggregate(Avg('hotness', default=0))
            .get('hotness__avg', 0)
        )

    def get_growth_threshold(self):
        """Return the growth threshold for that tier.

        The value is computed from the average growth (hotness) of add-ons in
        that tier plus the growth_threshold_before_flagging converted to
        decimal.

        It has a floor of 0."""
        return max(
            0, self.average_growth + (self.growth_threshold_before_flagging or 0) / 100
        )

    def get_growth_threshold_q_object(self):
        """Return Q object containing filters to apply to find add-ons over the
        computed growth threshold for that tier."""
        return Q(
            hotness__gt=self.get_growth_threshold(),
            **self.get_tier_boundaries(),
        )

    def get_abuse_threshold_q_object(self, *, block=False):
        """Return Q object containing filters to apply to find add-ons over the
        abuse threshold for that tier.

        `block` is a boolean - False for flagging threshold; True for blocking
        threshold.

        Depends on the queryset being annotated with
        `abuse_reports_count=UsageTier.get_abuse_count_subquery()` first."""
        threshold = (
            self.abuse_reports_ratio_threshold_before_flagging
            if not block
            else self.abuse_reports_ratio_threshold_before_blocking
        ) or 0
        return Q(
            abuse_reports_count__gte=Greatest('average_daily_users', 1)
            * threshold
            / 100,
            **self.get_tier_boundaries(),
        )

    @classmethod
    def get_abuse_count_subquery(cls):
        """Return the Subquery used to annotate `abuse_reports_count`. Needed
        to use get_abuse_threshold_q_object(block=False)."""
        abuse_reports_count_qs = (
            AbuseReport.objects.values('guid')
            .filter(
                ~AbuseReport.objects.__class__.is_individually_actionable_q(),
                guid=OuterRef('guid'),
                created__gte=datetime.now().date() - timedelta(days=14),
            )
            .annotate(guid_abuse_reports_count=Count('*'))
            .values('guid_abuse_reports_count')
            .order_by()
        )
        return abuse_reports_count_qs

    def get_rating_threshold_q_object(self, *, block=False):
        """Return Q object containing filters to apply to find add-ons over the
        rating threshold for that tier.

         `block` is a boolean - False for flagging threshold; True for blocking
        threshold.

        Depends on the queryset being annotated with
        `ratings_count=UsageTier.get_rating_count_subquery()` first."""
        threshold = (
            self.ratings_ratio_threshold_before_flagging
            if not block
            else self.ratings_ratio_threshold_before_blocking
        ) or 0
        return Q(
            ratings_count__gte=Greatest('average_daily_users', 1) * threshold / 100,
            **self.get_tier_boundaries(),
        )

    @classmethod
    def get_rating_count_subquery(cls):
        """Return the Subquery used to annotate `ratings_count`. Needed
        to use get_rating_threshold_q_object()."""
        ratings_count_qs = (
            Rating.without_replies.values('addon_id')
            .filter(
                addon_id=OuterRef('id'),
                created__gte=datetime.now().date() - timedelta(days=14),
            )
            .annotate(_ratings_count=Count('*'))
            .values('_ratings_count')
            .order_by()
        )
        return ratings_count_qs


class ChoiceEntryWithNHRAnnotationPrefix(ChoiceEntry):
    @property
    def annotation(self):
        """Annotation that querysets will use when returning the queue."""
        # This needs to match the classes in the CSS to show the right flag
        # for the right reason, and it's also used in the queue filter form,
        # and therefore in URLs that reviewers might have bookmarked - don't
        # change it lightly!
        return f'needs_human_review_{self.constant.lower()}'


class ChoicesWithNHRAnnotationPrefix(Choices):
    ChoiceEntryClass = ChoiceEntryWithNHRAnnotationPrefix


class NeedsHumanReview(ModelBase):
    """Model holding information about why a version was flagged for human
    review."""

    REASONS = ChoicesWithNHRAnnotationPrefix(
        ('BELONGS_TO_PROMOTED_GROUP', 14, 'Belongs to a promoted group'),
        ('ADDED_TO_PROMOTED_GROUP', 2, 'Was added to a promoted group'),
        ('DEVELOPER_REPLY', 6, 'Developer replied'),
        ('CINDER_ESCALATION', 10, 'Escalated for an abuse report, via cinder'),
        ('ABUSE_ADDON_VIOLATION', 11, 'Reported for abuse within the add-on'),
        (
            'ADDON_REVIEW_APPEAL',
            12,
            "Appeal of a reviewer's decision about a policy violation",
        ),
        ('CINDER_APPEAL_ESCALATION', 15, 'Escalated appeal via cinder'),
        (
            'SECOND_LEVEL_REQUEUE',
            16,
            'Re-enqueued in reviewer tools from 2nd level approval',
        ),
        ('ABUSE_REPORTS_THRESHOLD', 9, 'Over abuse reports threshold for usage tier'),
        ('RATINGS_THRESHOLD', 17, 'Over ratings threshold for usage tier'),
        (
            'PENDING_REJECTION_SOURCES_PROVIDED',
            5,
            'Sources provided while pending rejection',
        ),
        ('AUTO_APPROVAL_DISABLED', 13, 'Has auto-approval disabled'),
        ('SCANNER_ACTION', 1, 'Hit scanner rule'),
        ('HOTNESS_THRESHOLD', 3, 'Over growth threshold for usage tier'),
        ('INHERITANCE', 4, 'Previous version in channel had needs human review set'),
        (
            'MANUALLY_SET_BY_REVIEWER',
            7,
            'Manually set as needing human review by a reviewer',
        ),
        (
            'AUTO_APPROVED_PAST_APPROVAL_DELAY',
            8,
            'Auto-approved but still had an approval delay set in the past',
        ),
        ('VERSION_ROLLBACK', 18, 'Rollback to a previous version that was unreviewed'),
        ('UNKNOWN', 0, 'Unknown'),
    )
    REASONS.add_subset(
        'ABUSE_OR_APPEAL_RELATED',
        (
            'CINDER_ESCALATION',
            'ABUSE_ADDON_VIOLATION',
            'ADDON_REVIEW_APPEAL',
            'CINDER_APPEAL_ESCALATION',
            'SECOND_LEVEL_REQUEUE',
        ),
    )
    REASONS.add_subset(
        'NO_DUE_DATE_INHERITANCE',
        (
            'ABUSE_ADDON_VIOLATION',
            'CINDER_ESCALATION',
        ),
    )

    reason = models.SmallIntegerField(
        default=0, choices=REASONS.choices, editable=False
    )
    version = models.ForeignKey(on_delete=models.CASCADE, to=Version)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.version_id} - {self.get_reason_display()}'

    def save(self, *args, **kwargs):
        automatic_activity_log = not kwargs.pop('_no_automatic_activity_log', False)
        user = kwargs.pop('_user', None)
        if not self.pk and automatic_activity_log:
            activity.log_create(
                amo.LOG.NEEDS_HUMAN_REVIEW_AUTOMATIC,
                self.version,
                details={'comments': self.get_reason_display()},
                user=user or core.get_user() or get_task_user(),
            )
        return super().save(*args, **kwargs)

    @classmethod
    def set_on_addons_latest_signed_versions(cls, addons, reason):
        """Set needs human review on latest signed version in every channel for
        each addon in `addons`, if that version hasn't been reviewed or flagged
        for human review already, using `reason`. Due dates are
        staggered using get_staggered_review_due_date_generator().
        """
        due_date_generator = get_staggered_review_due_date_generator()
        used_generator_last_iteration = None
        due_date = None
        for addon in addons:
            if used_generator_last_iteration != []:
                # Only advance the generator if we used the previous due date or
                # it's the first iteration.
                due_date = next(due_date_generator)
            used_generator_last_iteration = (
                addon.set_needs_human_review_on_latest_versions(
                    due_date=due_date, reason=reason
                )
            )


class ReviewQueueHistory(ModelBase):
    # Note: a given Version can enter & leave the queue multiple times, and we
    # want to track each occurence, so it's not a OneToOneField.
    version = models.ForeignKey(Version, on_delete=models.CASCADE)
    original_due_date = models.DateTimeField(
        help_text='Original due date when the version entered the queue',
    )
    exit_date = models.DateTimeField(
        default=None,
        null=True,
        blank=True,
        help_text='When the version left the queue (regardless of reason)',
    )
    review_decision_log = models.ForeignKey(
        'activity.ActivityLog',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        help_text=(
            'Activity Log associated with the reviewer decision that caused '
            'the version to leave the queue'
        ),
    )

    class Meta:
        verbose_name_plural = 'Review Queue Histories'


@receiver(
    models.signals.post_save,
    sender=NeedsHumanReview,
    dispatch_uid='needshumanreview',
)
def update_due_date_for_needs_human_review_change(
    sender, instance=None, update_fields=None, **kwargs
):
    if update_fields is None or 'is_active' in update_fields:
        instance.version.reset_due_date()


class QueueCount(models.Model):
    date = models.DateField(auto_now_add=True)
    name = models.CharField(max_length=255)
    value = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('name', 'date'), name='queue_count_unique_name_date'
            ),
        ]

    def __str__(self):
        return f'{self.name} for {self.date}: {self.value}'
