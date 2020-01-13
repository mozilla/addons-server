from datetime import datetime, timedelta


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
        defaults={'auto_approval_delayed_until': in_twenty_four_hours})


def _delay_auto_approval_indefinitely(version):
    """Delay auto-approval for the whole add-on indefinitely."""
    # Always flag for human review.
    from olympia.addons.models import AddonReviewerFlags

    _flag_for_human_review(version)
    AddonReviewerFlags.objects.update_or_create(
        addon=version.addon,
        defaults={'auto_approval_delayed_until': datetime.max})
