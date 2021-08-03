from datetime import datetime, timedelta

from olympia.constants.scanners import MAD
from olympia.users.models import (
    EmailUserRestriction,
    IPNetworkUserRestriction,
    RESTRICTION_TYPES,
)


def _no_action(version):
    """Do nothing."""
    pass


def _flag_for_human_review(version):
    """Flag the version for human review."""
    version.update(needs_human_review=True)


def _delay_auto_approval(version):
    """Delay auto-approval for the whole add-on for 24 hours."""
    # Always flag for human review.
    from olympia.addons.models import AddonReviewerFlags

    _flag_for_human_review(version)
    in_twenty_four_hours = datetime.now() + timedelta(hours=24)
    AddonReviewerFlags.objects.update_or_create(
        addon=version.addon,
        defaults={'auto_approval_delayed_until': in_twenty_four_hours},
    )


def _delay_auto_approval_indefinitely(version):
    """Delay auto-approval for the whole add-on indefinitely."""
    # Always flag for human review.
    from olympia.addons.models import AddonReviewerFlags

    _flag_for_human_review(version)
    AddonReviewerFlags.objects.update_or_create(
        addon=version.addon, defaults={'auto_approval_delayed_until': datetime.max}
    )


def _delay_auto_approval_indefinitely_and_restrict(
    version, restriction_type=RESTRICTION_TYPES.SUBMISSION
):
    """Delay auto-approval for the whole add-on indefinitely, and restricts the
    user(s) and their IP(s)."""
    _delay_auto_approval_indefinitely(version)

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
    for user in users:
        EmailUserRestriction.objects.get_or_create(
            email_pattern=user.email, restriction_type=restriction_type
        )

    for ip in ips:
        IPNetworkUserRestriction.objects.get_or_create(
            network=f'{ip}/32', restriction_type=restriction_type
        )


def _delay_auto_approval_indefinitely_and_restrict_future_approvals(version):
    """Delay auto-approval for the whole add-on indefinitely, and restricts future
    approvals posted by the same user(s) and their IP(s)."""
    _delay_auto_approval_indefinitely_and_restrict(
        version, restriction_type=RESTRICTION_TYPES.APPROVAL
    )


def _flag_for_human_review_by_scanner(version, scanner):
    from olympia.versions.models import VersionReviewerFlags

    if scanner != MAD:
        raise ValueError('scanner should be MAD')

    VersionReviewerFlags.objects.update_or_create(
        version=version, defaults={'needs_human_review_by_mad': True}
    )
