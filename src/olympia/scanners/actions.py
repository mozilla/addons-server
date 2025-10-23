from datetime import datetime, timedelta

from olympia.abuse.utils import reject_and_block_addons
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.users.models import (
    RESTRICTION_TYPES,
    EmailUserRestriction,
    IPNetworkUserRestriction,
)


def _no_action(*, version, rule):
    """Do nothing."""
    pass


def _flag_for_human_review(*, version, rule):
    """Flag the version for human review if it hasn't been flagged by a scanner
    already."""
    from olympia.reviewers.models import NeedsHumanReview

    # Check if the version has already been flagged by a scanner action.
    # If it has not, then we just need to create a flag.
    # (Can't use get_or_create(), there is no uniqueness constraint)
    if not version.needshumanreview_set.filter(
        reason=NeedsHumanReview.REASONS.SCANNER_ACTION
    ).exists():
        version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.SCANNER_ACTION
        )
        return True
    # If it has been flagged already... then return True only if one of the
    # flags is active still.
    return version.needshumanreview_set.filter(
        reason=NeedsHumanReview.REASONS.SCANNER_ACTION, is_active=True
    ).exists()


def _delay_auto_approval(*, version, rule):
    """Delay auto-approval for both channels on the whole add-on for 24 hours.

    If delay was already set for either channel, only override it if the new
    delay is further in the future."""
    # Always try to flag for human review. If that returns False it means we
    # already flagged before so we don't want to repeat the rest.
    if not _flag_for_human_review(version=version, rule=rule):
        return False

    in_twenty_four_hours = datetime.now() + timedelta(hours=24)
    version.addon.set_auto_approval_delay_if_higher_than_existing(in_twenty_four_hours)
    # When introducing a short auto-approval delay, reset the due date to match
    # the delay, unless it's already set to before the delay expires. That way
    # reviewers are incentivized to look at those versions before they go back
    # to being auto-approved.
    due_date = min(version.due_date or in_twenty_four_hours, in_twenty_four_hours)
    version.reset_due_date(due_date=due_date)
    return True


def _delay_auto_approval_indefinitely(*, version, rule):
    """Delay auto-approval for the whole add-on indefinitely."""
    from olympia.addons.models import AddonReviewerFlags

    # Always try to flag for human review. If that returns False it means we
    # already flagged before so we don't want to repeat the rest.
    if not _flag_for_human_review(version=version, rule=rule):
        return False

    AddonReviewerFlags.objects.update_or_create(
        addon=version.addon,
        defaults={
            'auto_approval_delayed_until': datetime.max,
            'auto_approval_delayed_until_unlisted': datetime.max,
        },
    )
    return True


def _restrict_future_approvals(*, version, rule, restriction_type):
    # Collect users and their IPs
    upload = (
        version.addon.fileupload_set.all()
        .select_related('user')
        .filter(version=version.version)
        .first()
    )
    users = set(version.addon.authors.all())
    if upload:
        users.add(upload.user)
    ips = {user.last_login_ip for user in users if user.last_login_ip}
    if upload and upload.ip_address:
        ips.add(upload.ip_address)

    # Restrict all those IPs and users.
    restriction_defaults = {
        'reason': (
            'Automatically added because of a match by rule '
            f'"{str(rule)[:150]}" on Addon {version.addon.pk} Version {version.pk}.'
        ),
    }
    for user in users:
        EmailUserRestriction.objects.get_or_create(
            email_pattern=user.email,
            restriction_type=restriction_type,
            defaults=restriction_defaults,
        )

    for ip in ips:
        network = IPNetworkUserRestriction.network_from_ip(ip)
        IPNetworkUserRestriction.objects.get_or_create(
            network=network,
            restriction_type=restriction_type,
            defaults=restriction_defaults,
        )


def _delay_auto_approval_indefinitely_and_restrict(
    *, version, rule, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
):
    """Delay auto-approval for the whole add-on indefinitely, and restricts the
    user(s) and their IP(s)."""
    # Always _delay_auto_approval_indefinitely() returns False it means we
    # already flagged before so we don't want to repeat the rest.
    if not _delay_auto_approval_indefinitely(version=version, rule=rule):
        return False

    _restrict_future_approvals(
        version=version, rule=rule, restriction_type=restriction_type
    )
    return True


def _delay_auto_approval_indefinitely_and_restrict_future_approvals(*, version, rule):
    """Delay auto-approval for the whole add-on indefinitely, and restricts future
    approvals posted by the same user(s) and their IP(s)."""
    return _delay_auto_approval_indefinitely_and_restrict(
        version=version, rule=rule, restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
    )


def _disable_and_block(*, version, rule):
    """Force disable the whole add-on and block all its versions."""
    # This is final, and meant as an aggressive last-resort, so there are no
    # checks on whether or not the version has been flagged by a scanner
    # before. Instead, we check the UsageTier the Addon belongs to, and only
    # execute if the UsageTier allows it. If not, we delay auto approval
    # instead (which would flag too).
    from olympia.abuse.models import ContentDecision

    addon = version.addon
    usage_tier = addon.get_usage_tier()
    successful_appeal = ContentDecision.objects.filter(
        addon=addon,
        action__in=DECISION_ACTIONS.NON_OFFENDING.values,
        cinder_job__appealed_decisions__action__in=DECISION_ACTIONS.REMOVING.values,
    )

    if (
        usage_tier
        and usage_tier.disable_and_block_action_available
        and not successful_appeal.exists()
    ):
        _restrict_future_approvals(
            version=version,
            rule=rule,
            restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL,
        )
        reject_and_block_addons([addon])
    else:
        _delay_auto_approval_indefinitely(version=version, rule=rule)
