from datetime import datetime

import olympia.core.logger
from olympia import amo
from olympia.activity import log_create
from olympia.users.utils import get_task_user
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.amo.blocklist')


def block_activity_log_save(obj, *, change, submission_obj):
    from .models import BlockType

    action = amo.LOG.BLOCKLIST_BLOCK_EDITED if change else amo.LOG.BLOCKLIST_BLOCK_ADDED
    action_version = amo.LOG.BLOCKLIST_VERSION_BLOCKED
    addon_versions = {ver.id: ver.version for ver in obj.addon_versions}
    blocked_versions = sorted(
        ver.version for ver in obj.addon_versions if ver.is_blocked
    )
    changed_version_ids = [
        v_id for v_id in submission_obj.changed_version_ids if v_id in addon_versions
    ]
    changed_versions = sorted(addon_versions[ver_id] for ver_id in changed_version_ids)

    details = {
        'guid': obj.guid,
        'blocked_versions': blocked_versions,
        'added_versions': changed_versions,
        'url': obj.url,
        'reason': obj.reason,
        'comments': f'{len(changed_versions)} versions added to block; '
        f'{len(blocked_versions)} total versions now blocked.',
    }

    details['signoff_state'] = submission_obj.SIGNOFF_STATES.for_value(
        submission_obj.signoff_state
    ).display
    if submission_obj.signoff_by:
        details['signoff_by'] = submission_obj.signoff_by.id
    details['block_type'] = submission_obj.block_type
    if submission_obj.block_type == BlockType.SOFT_BLOCKED:
        action_version = amo.LOG.BLOCKLIST_VERSION_SOFT_BLOCKED

    log_create(action, obj.addon, obj.guid, obj, details=details, user=obj.updated_by)
    log_create(
        action_version,
        *((Version, version_id) for version_id in changed_version_ids),
        obj,
        details={},
        user=obj.updated_by,
    )

    if submission_obj.signoff_by:
        log_create(
            amo.LOG.BLOCKLIST_SIGNOFF,
            obj.addon,
            obj.guid,
            action.action_class,
            obj,
            user=submission_obj.signoff_by,
        )


def block_activity_log_delete(obj, deleted, *, submission_obj=None, delete_user=None):
    assert submission_obj or delete_user
    addon_versions = {ver.id: ver.version for ver in obj.addon_versions}
    blocked_versions = (
        sorted(ver.version for ver in obj.addon_versions if ver.is_blocked)
        if not deleted
        else []
    )
    changed_version_ids = (
        [v_id for v_id in submission_obj.changed_version_ids if v_id in addon_versions]
        if submission_obj
        else sorted(ver.id for ver in obj.addon_versions if not ver.is_blocked)
    )
    changed_versions = sorted(
        addon_versions[ver_id]
        for ver_id in changed_version_ids
        if ver_id in addon_versions
    )

    details = {
        'guid': obj.guid,
        'blocked_versions': blocked_versions,
        'removed_versions': changed_versions,
        'url': obj.url,
        'reason': obj.reason,
        'comments': f'{len(changed_versions)} versions removed from block; '
        f'{len(blocked_versions)} total versions now blocked.',
    }
    action = (
        amo.LOG.BLOCKLIST_BLOCK_EDITED
        if not deleted
        else amo.LOG.BLOCKLIST_BLOCK_DELETED
    )

    if submission_obj:
        details['signoff_state'] = submission_obj.SIGNOFF_STATES.for_value(
            submission_obj.signoff_state
        ).display
        if submission_obj.signoff_by:
            details['signoff_by'] = submission_obj.signoff_by.id

    log_create(
        *[action, *([obj.addon] if obj.addon else []), obj.guid, obj],
        details=details,
        user=submission_obj.updated_by if submission_obj else delete_user,
    )
    log_create(
        amo.LOG.BLOCKLIST_VERSION_UNBLOCKED,
        *((Version, version_id) for version_id in changed_version_ids),
        obj,
        user=submission_obj.updated_by if submission_obj else delete_user,
    )

    if submission_obj and submission_obj.signoff_by:
        args = [
            amo.LOG.BLOCKLIST_SIGNOFF,
            *([obj.addon] if obj.addon else []),
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

    task_user = get_task_user()
    activity_user = block.updated_by or get_task_user()
    human_review = activity_user != task_user
    review = ReviewBase(
        addon=block.addon, version=None, user=activity_user, human_review=human_review
    )
    versions_to_reject = [
        ver
        for ver in block.addon_versions
        # We don't need to reject versions from older deleted instances
        # and already disabled files
        if ver.addon == block.addon
        and ver.id in submission.changed_version_ids
        and ver.file.status != amo.STATUS_DISABLED
        and ver.deleted is False
    ]
    if versions_to_reject:
        review.set_data(
            {
                'versions': versions_to_reject,
                'comments': block.reason,
                'is_addon_being_blocked': True,
                'is_addon_being_disabled': submission.disable_addon,
            }
        )
        review.auto_reject_multiple_versions()

    if human_review:
        for version in block.addon_versions:
            # Clear active NeedsHumanReview on all blocked versions, if a human has
            # reviewed we consider that the admin looked at them before blocking (don't
            # limit to versions we are rejecting, which is only a subset).
            review.clear_specific_needs_human_review_flags(version)


def save_versions_to_blocks(guids, submission, *, overwrite_block_metadata=True):
    from olympia.addons.models import GuidAlreadyDeniedError

    from .models import Block, BlockVersion

    modified_datetime = datetime.now()

    blocks = Block.get_blocks_from_guids(guids)
    for block in blocks:
        change = bool(block.id)
        if change:
            block.modified = modified_datetime
            should_override_block_metadata = overwrite_block_metadata
        else:
            should_override_block_metadata = True
        block.updated_by = submission.updated_by
        if submission.reason is not None and should_override_block_metadata:
            block.reason = submission.reason
        if submission.url is not None and should_override_block_metadata:
            block.url = submission.url
        block.average_daily_users_snapshot = block.current_adu
        # And now update the BlockVersion instances - instances to add first
        block_versions_to_create = []
        block_versions_to_update = []
        for version in block.addon_versions:
            if version.id in submission.changed_version_ids:
                if version.is_blocked:
                    block_version = version.blockversion
                    block_versions_to_update.append(block_version)
                else:
                    block_version = BlockVersion(block=block, version=version)
                    block_versions_to_create.append(block_version)
                    version.blockversion = block_version
                block_version.block_type = submission.block_type
        if not block_versions_to_create and not change:
            # If we have no versions to block and it's a new Block don't do anything.
            # Note: we shouldn't have gotten this far with such a guid - it would have
            # been raised as a validation error in the form.
            continue
        block.save()
        # Update existing BlockVersion in bulk - the only field to update is
        # 'block_type'.
        BlockVersion.objects.bulk_update(
            block_versions_to_update, fields=['block_type']
        )
        # Add new BlockVersion in bulk.
        BlockVersion.objects.bulk_create(block_versions_to_create)

        if submission.id:
            block.submission.add(submission)
        block_activity_log_save(
            block,
            change=change,
            submission_obj=submission,
        )
        disable_versions_for_block(block, submission)
        if submission.disable_addon:
            if block.addon.status == amo.STATUS_DELETED:
                try:
                    block.addon.deny_resubmission()
                except GuidAlreadyDeniedError:
                    pass
            else:
                # Disabling the add-on triggers a bunch of things so make sure
                # it's done last, after we've gone through
                # disable_versions_for_block().
                block.addon.update(status=amo.STATUS_DISABLED)

    return blocks


def delete_versions_from_blocks(guids, submission):
    from .models import Block, BlockVersion

    modified_datetime = datetime.now()

    blocks = Block.get_blocks_from_guids(guids)
    for block in blocks:
        if not block.id:
            continue
        block.modified = modified_datetime

        BlockVersion.objects.filter(
            block=block, version_id__in=submission.changed_version_ids
        ).delete()

        if BlockVersion.objects.filter(block=block).exists():
            # if there are still other versions blocked update the metadata
            block.updated_by = submission.updated_by
            if submission.reason is not None:
                block.reason = submission.reason
            if submission.url is not None:
                block.url = submission.url
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


def get_mlbf_base_id_config_key(block_type, compat: bool = False):
    """
    We use compat to return the old singular config key for hard blocks.
    This allows us to migrate writes to the new plural key right now without
    losing access to the old existing key when deploying this patch.
    """
    from olympia.blocklist.models import BlockType

    if compat and block_type == BlockType.BLOCKED:
        return amo.config_keys.BLOCKLIST_MLBF_BASE_ID
    return getattr(amo.config_keys, f'BLOCKLIST_MLBF_BASE_ID_{block_type.name.upper()}')
