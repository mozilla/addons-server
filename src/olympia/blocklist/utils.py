from datetime import datetime

import olympia.core.logger
from olympia import amo
from olympia.activity import log_create
from olympia.users.utils import get_task_user


log = olympia.core.logger.getLogger('z.amo.blocklist')


def add_version_log_for_blocked_versions(obj, al, submission_obj=None):
    from olympia.activity.models import VersionLog

    VersionLog.objects.bulk_create(
        [
            VersionLog(activity_log=al, version=version)
            for version in obj.addon_versions
            if version.is_blocked
            or (submission_obj and version.id in submission_obj.changed_version_ids)
        ]
    )


def block_activity_log_save(
    obj,
    change,
    submission_obj=None,
):
    action = amo.LOG.BLOCKLIST_BLOCK_EDITED if change else amo.LOG.BLOCKLIST_BLOCK_ADDED
    version_ids = sorted(ver.id for ver in obj.addon_versions if ver.is_blocked)
    details = {
        'guid': obj.guid,
        'versions': version_ids,
        'url': obj.url,
        'reason': obj.reason,
        'comments': f'{len(version_ids)} versions blocked.',
    }
    if submission_obj:
        details['signoff_state'] = submission_obj.SIGNOFF_STATES.get(
            submission_obj.signoff_state
        )
        if submission_obj.signoff_by:
            details['signoff_by'] = submission_obj.signoff_by.id
    addon = obj.addon
    al = log_create(action, addon, obj.guid, obj, details=details, user=obj.updated_by)
    if submission_obj and submission_obj.signoff_by:
        log_create(
            amo.LOG.BLOCKLIST_SIGNOFF,
            addon,
            obj.guid,
            action.action_class,
            obj,
            user=submission_obj.signoff_by,
        )

    add_version_log_for_blocked_versions(obj, al)


def block_activity_log_delete(obj, deleted, *, submission_obj=None, delete_user=None):
    assert submission_obj or delete_user
    version_ids = [ver.id for ver in obj.addon_versions if ver.is_blocked]
    details = {
        'guid': obj.guid,
        'versions': version_ids,
        'url': obj.url,
        'reason': obj.reason,
        'comments': f'{len(version_ids)} versions unblocked.',
    }
    action = (
        amo.LOG.BLOCKLIST_BLOCK_EDITED
        if not deleted
        else amo.LOG.BLOCKLIST_BLOCK_DELETED
    )

    if submission_obj:
        details['signoff_state'] = submission_obj.SIGNOFF_STATES.get(
            submission_obj.signoff_state
        )
        if submission_obj.signoff_by:
            details['signoff_by'] = submission_obj.signoff_by.id
    addon = obj.addon
    al = log_create(
        *[action, *([addon] if addon else []), obj.guid, obj],
        details=details,
        user=submission_obj.updated_by if submission_obj else delete_user,
    )
    if addon:
        add_version_log_for_blocked_versions(obj, al, submission_obj)
    if submission_obj and submission_obj.signoff_by:
        args = [
            amo.LOG.BLOCKLIST_SIGNOFF,
            *([addon] if addon else []),
            obj.guid,
            action.action_class,
            obj,
        ]
        log_create(*args, user=submission_obj.signoff_by)


def splitlines(text):
    return [line.strip() for line in str(text or '').splitlines()]


def datetime_to_ts(dt=None):
    """Returns the timestamp used for MLBF identifiers.
    Calculated as number of milliseconds from the unix epoc."""
    return int((dt or datetime.now()).timestamp() * 1000)


def disable_versions_for_block(block, submission):
    """Disable appropriate addon versions that are affected by the Block."""
    from olympia.reviewers.utils import ReviewBase

    review = ReviewBase(
        addon=block.addon,
        version=None,
        user=get_task_user(),
        review_type='pending',
        human_review=False,
    )
    versions_to_reject = [
        ver
        for ver in block.addon_versions
        # We don't need to reject versions from older deleted instances
        # and already disabled files
        if ver.addon == block.addon
        and ver.id in submission.changed_version_ids
        and ver.file.status != amo.STATUS_DISABLED
    ]
    review.set_data({'versions': versions_to_reject})
    review.reject_multiple_versions()

    for version in block.addon_versions:
        # Clear active NeedsHumanReview on all blocked versions, we consider
        # that the admin looked at them before blocking (don't limit to
        # versions we are rejecting, which is only a subset).
        review.clear_specific_needs_human_review_flags(version)


def save_versions_to_blocks(guids, submission, *, fields_to_set):
    from olympia.addons.models import GuidAlreadyDeniedError

    from .models import Block, BlockVersion

    common_args = {field: getattr(submission, field) for field in fields_to_set}
    modified_datetime = datetime.now()

    blocks = Block.get_blocks_from_guids(guids)
    Block.preload_addon_versions(blocks)
    for block in blocks:
        change = bool(block.id)
        if change:
            setattr(block, 'modified', modified_datetime)
        for field, val in common_args.items():
            setattr(block, field, val)
        block.average_daily_users_snapshot = block.current_adu
        block.save()
        # And now update the BlockVersion instances - instances to add first
        block_versions_to_create = []
        for version in block.addon_versions:
            if version.id in submission.changed_version_ids and (
                not change or not version.is_blocked
            ):
                block_version = BlockVersion(block=block, version=version)
                block_versions_to_create.append(block_version)
                version.blockversion = block_version
        BlockVersion.objects.bulk_create(block_versions_to_create)

        if submission.id:
            block.submission.add(submission)
        block_activity_log_save(
            block,
            change=change,
            submission_obj=submission if submission.id else None,
        )
        disable_versions_for_block(block, submission)
        if submission.disable_addon:
            if block.addon.status == amo.STATUS_DELETED:
                try:
                    block.addon.deny_resubmission()
                except GuidAlreadyDeniedError:
                    pass
            else:
                block.addon.update(status=amo.STATUS_DISABLED)

    return blocks


def delete_versions_from_blocks(guids, submission, *, fields_to_set):
    from .models import Block, BlockVersion

    common_args = {field: getattr(submission, field) for field in fields_to_set}
    modified_datetime = datetime.now()

    blocks = Block.get_blocks_from_guids(guids)
    Block.preload_addon_versions(blocks)
    for block in blocks:
        setattr(block, 'modified', modified_datetime)

        BlockVersion.objects.filter(
            block=block, version_id__in=submission.changed_version_ids
        ).delete()

        if BlockVersion.objects.filter(block=block).exists():
            # if there are still other versions blocked update the metadata
            for field, val in common_args.items():
                setattr(block, field, val)
            block.average_daily_users_snapshot = block.current_adu
            block.save()
            should_delete = False

            if submission.id:
                block.submission.add(submission)
        else:
            # otherwise we can delete the Block instance
            should_delete = True

        block_activity_log_delete(
            block,
            deleted=should_delete,
            submission_obj=submission if submission.id else None,
        )
        if should_delete:
            block.delete()

    return blocks
