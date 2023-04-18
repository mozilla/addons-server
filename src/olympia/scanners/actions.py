from datetime import datetime, timedelta

from olympia.constants.scanners import MAD
from olympia.users.models import (
    EmailUserRestriction,
    IPNetworkUserRestriction,
    RESTRICTION_TYPES,
)


def _no_action(*, version, rule):
    """Do nothing."""
    pass


def _flag_for_human_review(*, version, rule):
    """Flag the version for human review."""
    version.update(needs_human_review=True)


def _delay_auto_approval(*, version, rule):
    """Delay auto-approval for both channels on the whole add-on for 24 hours.

    If delay was already set for either channel, only override it if the new
    delay is further in the future."""
    # Always flag for human review.
    _flag_for_human_review(version=version, rule=rule)
    in_twenty_four_hours = datetime.now() + timedelta(hours=24)
    version.addon.set_auto_approval_delay_if_higher_than_existing(in_twenty_four_hours)
    # When introducing a short auto-approval delay, reset the due date to match
    # the delay, unless it's already set to before the delay expires. That way
    # reviewers are incentivized to look at those versions before they go back
    # to being auto-approved.
    due_date = min(version.due_date or in_twenty_four_hours, in_twenty_four_hours)
    version.reset_due_date(due_date=due_date)


def _delay_auto_approval_indefinitely(*, version, rule):
    """Delay auto-approval for the whole add-on indefinitely."""
    # Always flag for human review.
    from olympia.addons.models import AddonReviewerFlags

    _flag_for_human_review(version=version, rule=rule)
    AddonReviewerFlags.objects.update_or_create(
        addon=version.addon,
        defaults={
            'auto_approval_delayed_until': datetime.max,
            'auto_approval_delayed_until_unlisted': datetime.max,
        },
    )


def _delay_auto_approval_indefinitely_and_restrict(
    *, version, rule, restriction_type=RESTRICTION_TYPES.ADDON_SUBMISSION
):
    """Delay auto-approval for the whole add-on indefinitely, and restricts the
    user(s) and their IP(s)."""
    _delay_auto_approval_indefinitely(version=version, rule=rule)

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
        IPNetworkUserRestriction.objects.get_or_create(
            network=f'{ip}/32',
            restriction_type=restriction_type,
            defaults=restriction_defaults,
        )


def _delay_auto_approval_indefinitely_and_restrict_future_approvals(*, version, rule):
    """Delay auto-approval for the whole add-on indefinitely, and restricts future
    approvals posted by the same user(s) and their IP(s)."""
    _delay_auto_approval_indefinitely_and_restrict(
        version=version, rule=rule, restriction_type=RESTRICTION_TYPES.ADDON_APPROVAL
    )


def _flag_for_human_review_by_scanner(*, version, rule, scanner):
    from olympia.versions.models import VersionReviewerFlags

    if scanner != MAD:
        raise ValueError('scanner should be MAD')

    VersionReviewerFlags.objects.update_or_create(
        version=version, defaults={'needs_human_review_by_mad': True}
    )
