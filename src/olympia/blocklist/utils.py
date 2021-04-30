from datetime import datetime
import re

from django.conf import settings

import olympia.core.logger
from olympia import amo
from olympia.activity import log_create
from olympia.constants.blocklist import REMOTE_SETTINGS_COLLECTION_LEGACY
from olympia.lib.remote_settings import RemoteSettings
from olympia.users.utils import get_task_user


log = olympia.core.logger.getLogger('z.amo.blocklist')


def add_version_log_for_blocked_versions(obj, old_obj, al):
    from olympia.activity.models import VersionLog

    VersionLog.objects.bulk_create(
        [
            VersionLog(activity_log=al, version_id=version.id)
            for version in obj.addon_versions
            if obj.is_version_blocked(version.version)
            or old_obj.is_version_blocked(version.version)
        ]
    )


def block_activity_log_save(obj, change, submission_obj=None, old_obj=None):
    action = amo.LOG.BLOCKLIST_BLOCK_EDITED if change else amo.LOG.BLOCKLIST_BLOCK_ADDED
    legacy_inclusion = getattr(
        submission_obj if submission_obj else obj, 'in_legacy_blocklist'
    )
    details = {
        'guid': obj.guid,
        'min_version': obj.min_version,
        'max_version': obj.max_version,
        'url': obj.url,
        'reason': obj.reason,
        'include_in_legacy': legacy_inclusion,
        'comments': f'Versions {obj.min_version} - {obj.max_version} blocked.',
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

    add_version_log_for_blocked_versions(obj, old_obj or obj, al)


def block_activity_log_delete(obj, *, submission_obj=None, delete_user=None):
    assert submission_obj or delete_user
    details = {
        'guid': obj.guid,
        'min_version': obj.min_version,
        'max_version': obj.max_version,
        'url': obj.url,
        'reason': obj.reason,
        'include_in_legacy': obj.in_legacy_blocklist,
        'comments': f'Versions {obj.min_version} - {obj.max_version} unblocked.',
    }
    if submission_obj:
        details['signoff_state'] = submission_obj.SIGNOFF_STATES.get(
            submission_obj.signoff_state
        )
        if submission_obj.signoff_by:
            details['signoff_by'] = submission_obj.signoff_by.id
    addon = obj.addon
    args = (
        [amo.LOG.BLOCKLIST_BLOCK_DELETED] + ([addon] if addon else []) + [obj.guid, obj]
    )
    al = log_create(
        *args,
        details=details,
        user=submission_obj.updated_by if submission_obj else delete_user,
    )
    if addon:
        add_version_log_for_blocked_versions(obj, obj, al)
    if submission_obj and submission_obj.signoff_by:
        args = (
            [amo.LOG.BLOCKLIST_SIGNOFF]
            + ([addon] if addon else [])
            + [obj.guid, amo.LOG.BLOCKLIST_BLOCK_DELETED.action_class, obj]
        )
        log_create(*args, user=submission_obj.signoff_by)


def splitlines(text):
    return [line.strip() for line in str(text or '').splitlines()]


def legacy_publish_blocks(blocks):
    bucket = settings.REMOTE_SETTINGS_WRITER_BUCKET
    server = RemoteSettings(bucket, REMOTE_SETTINGS_COLLECTION_LEGACY)
    for block in blocks:
        needs_creating = not block.legacy_id

        if block.is_imported_from_legacy_regex:
            log.info(
                f'Block [{block.guid}] was imported from a regex guid so '
                "can't be safely updated.  Skipping."
            )
            continue
        data = {
            'guid': block.guid,
            'details': {
                'bug': block.url,
                'why': block.reason,
                'name': str(block.reason).partition('.')[0],  # required
            },
            'enabled': True,
            'versionRange': [
                {
                    'severity': 3,  # Always high severity now.
                    'minVersion': block.min_version,
                    'maxVersion': block.max_version,
                }
            ],
        }
        if needs_creating:
            record = server.publish_record(data)
            block.update(legacy_id=record.get('id', ''))
        else:
            server.publish_record(data, block.legacy_id)

    server.complete_session()


def legacy_delete_blocks(blocks):
    bucket = settings.REMOTE_SETTINGS_WRITER_BUCKET
    server = RemoteSettings(bucket, REMOTE_SETTINGS_COLLECTION_LEGACY)
    for block in blocks:
        if block.legacy_id:
            if block.is_imported_from_legacy_regex:
                log.info(
                    f'Block [{block.guid}] was imported from a regex guid so '
                    "can't be safely deleted.  Skipping."
                )
            else:
                server.delete_record(block.legacy_id)
            block.update(legacy_id='')
    server.complete_session()


# Started out based on the regexs in the following url but needed some changes:
# https://dxr.mozilla.org/mozilla-central/source/toolkit/mozapps/extensions/Blocklist.jsm  # noqa

# The whole ID should be surrounded by literal ().
# IDs may contain alphanumerics, _, -, {}, @ and a literal '.'
# They may also contain backslashes (needed to escape the {} and dot)
# We filter out backslash escape sequences (like `\w`) separately
IS_MULTIPLE_ID_SUB_REGEX = r'\([\\\w .{}@-]+\)'
# Find regular expressions of the form:
# /^((id1)|(id2)|(id3)|...|(idN))$/
# The outer set of parens enclosing the entire list of IDs is optional.
IS_MULTIPLE_IDS = re.compile(
    # Start with literal ^ then an optional `(``
    r'^\^\(?'
    # Then at least one ID in parens ().
    + IS_MULTIPLE_ID_SUB_REGEX
    # Followed by any number of IDs in () separated by pipes.
    + r'(?:\|'
    + IS_MULTIPLE_ID_SUB_REGEX
    + r')*'
    # Finally, we need to end with a literal sequence )$
    #  (the leading `)` is optional like at the start)
    + r'\)?\$$'
)
# Check for a backslash followed by anything other than a literal . or curlies
REGEX_ESCAPE_SEQS = re.compile(r'\\[^.{}]')
# Used to remove the following 3 things:
# leading literal ^(
#    plus an optional (
# any backslash
# trailing literal )$
#    plus an optional ) before the )$
REGEX_REMOVAL_REGEX = re.compile(r'^\^\(\(?|\\|\)\)?\$$')
GUID_SPLIT = re.compile(r'\)\|\(')


def datetime_to_ts(dt=None):
    """Returns the timestamp used for MLBF identifiers.
    Calculated as number of milliseconds from the unix epoc."""
    return int((dt or datetime.now()).timestamp() * 1000)


def split_regex_to_list(guid_re):
    if not IS_MULTIPLE_IDS.match(guid_re) or REGEX_ESCAPE_SEQS.match(guid_re):
        return
    trimmed = REGEX_REMOVAL_REGEX.sub('', guid_re)
    return GUID_SPLIT.split(trimmed)


def disable_addon_for_block(block):
    """Disable appropriate addon versions that are affected by the Block, and
    the addon too if 0 - *."""
    from .models import Block
    from olympia.reviewers.utils import ReviewBase

    review = ReviewBase(
        request=None,
        addon=block.addon,
        version=None,
        review_type='pending',
        user=get_task_user(),
    )
    review.set_data(
        {
            'versions': [
                ver
                for ver in block.addon_versions
                # We don't need to reject versions from older deleted instances
                if ver.addon == block.addon and block.is_version_blocked(ver.version)
            ]
        }
    )
    review.reject_multiple_versions()

    for version in review.data['versions']:
        # Clear needs_human_review on rejected versions, we consider that
        # the admin looked at them before blocking.
        review.clear_specific_needs_human_review_flags(version)

    if block.min_version == Block.MIN and block.max_version == Block.MAX:
        if block.addon.status == amo.STATUS_DELETED:
            block.addon.deny_resubmission()
        else:
            block.addon.update(status=amo.STATUS_DISABLED)


def save_guids_to_blocks(guids, submission, *, fields_to_set):
    from .models import Block

    common_args = {field: getattr(submission, field) for field in fields_to_set}
    modified_datetime = datetime.now()

    blocks = Block.get_blocks_from_guids(guids)
    Block.preload_addon_versions(blocks)
    for block in blocks:
        change = bool(block.id)
        if change:
            block_obj_before_change = Block(
                min_version=block.min_version, max_version=block.max_version
            )
            setattr(block, 'modified', modified_datetime)
        else:
            block_obj_before_change = None
        for field, val in common_args.items():
            setattr(block, field, val)
        block.average_daily_users_snapshot = block.current_adu
        block.save()
        if submission.id:
            block.submission.add(submission)
        block_activity_log_save(
            block,
            change=change,
            submission_obj=submission if submission.id else None,
            old_obj=block_obj_before_change,
        )
        disable_addon_for_block(block)

    return blocks
