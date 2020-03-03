import math

from filtercascade import FilterCascade

import olympia.core.logger
from olympia import amo
from olympia.activity import log_create
from olympia.lib.kinto import KintoServer


log = olympia.core.logger.getLogger('z.amo.blocklist')

KINTO_BUCKET = 'staging'
KINTO_COLLECTION_LEGACY = 'addons'
KINTO_COLLECTION_MLBF = 'addons-mblf'


def add_version_log_for_blocked_versions(obj, al):
    from olympia.activity.models import VersionLog

    VersionLog.objects.bulk_create([
        VersionLog(activity_log=al, version_id=id_chan[0])
        for version, id_chan in obj.addon_versions.items()
        if obj.is_version_blocked(version)
    ])


def block_activity_log_save(obj, change, submission_obj=None):
    action = (
        amo.LOG.BLOCKLIST_BLOCK_EDITED if change else
        amo.LOG.BLOCKLIST_BLOCK_ADDED)
    details = {
        'guid': obj.guid,
        'min_version': obj.min_version,
        'max_version': obj.max_version,
        'url': obj.url,
        'reason': obj.reason,
        'include_in_legacy': obj.include_in_legacy,
        'comments': f'Versions {obj.min_version} - {obj.max_version} blocked.',
    }
    if submission_obj:
        details['signoff_state'] = submission_obj.SIGNOFF_STATES.get(
            submission_obj.signoff_state)
        if submission_obj.signoff_by:
            details['signoff_by'] = submission_obj.signoff_by.id
    al = log_create(
        action, obj.addon, obj.guid, obj, details=details, user=obj.updated_by)
    if submission_obj and submission_obj.signoff_by:
        log_create(
            amo.LOG.BLOCKLIST_SIGNOFF,
            obj.addon,
            obj.guid,
            action.action_class,
            obj,
            user=submission_obj.signoff_by)

    add_version_log_for_blocked_versions(obj, al)


def block_activity_log_delete(obj, submission_obj):
    details = {
        'guid': obj.guid,
        'min_version': obj.min_version,
        'max_version': obj.max_version,
        'url': obj.url,
        'reason': obj.reason,
        'include_in_legacy': obj.include_in_legacy,
        'comments': f'Versions {obj.min_version} - {obj.max_version} blocked.',
    }
    if submission_obj:
        details['signoff_state'] = submission_obj.SIGNOFF_STATES.get(
            submission_obj.signoff_state)
        if submission_obj.signoff_by:
            details['signoff_by'] = submission_obj.signoff_by.id
    args = (
        [amo.LOG.BLOCKLIST_BLOCK_DELETED] +
        ([obj.addon] if obj.addon else []) +
        [obj.guid, obj])
    al = log_create(
        *args, details=details, user=submission_obj.updated_by)
    if obj.addon:
        add_version_log_for_blocked_versions(obj, al)
    if submission_obj.signoff_by:
        args = (
            [amo.LOG.BLOCKLIST_SIGNOFF] +
            ([obj.addon] if obj.addon else []) +
            [obj.guid, amo.LOG.BLOCKLIST_BLOCK_DELETED.action_class, obj])
        log_create(*args, user=submission_obj.signoff_by)


def splitlines(text):
    return [line.strip() for line in str(text or '').splitlines()]


def get_blocked_guids():
    from olympia.addons.models import Addon
    from olympia.blocklist.models import Block

    blocks = Block.objects.all()
    blocks_guids = [block.guid for block in blocks]
    addons_dict = Addon.unfiltered.in_bulk(blocks_guids, field_name='guid')
    for block in blocks:
        block.addon = addons_dict.get(block.guid)
    Block.preload_addon_versions(blocks)
    all_versions = {}
    # collect all the blocked versions
    for block in blocks:
        is_all_versions = (
            block.min_version == Block.MIN and
            block.max_version == Block.MAX)
        versions = {
            version_id: (block.guid, version)
            for version, (version_id, _) in block.addon_versions.items()
            if is_all_versions or block.is_version_blocked(version)}
        all_versions.update(versions)
    return all_versions.values()


def get_all_guids():
    from olympia.versions.models import Version

    return Version.objects.values_list('addon__guid', 'version')


def hash_filter_inputs(input_list, salt):
    return [
        f'{salt}:{guid}:{version}' for (guid, version) in input_list]


def generate_mlbf(stats, salt, *, blocked=None, not_blocked=None):
    """Based on:
    https://github.com/mozilla/crlite/blob/master/create_filter_cascade/certs_to_crlite.py
    """
    blocked = hash_filter_inputs(blocked or get_blocked_guids(), salt)
    not_blocked = hash_filter_inputs(not_blocked or get_all_guids(), salt)

    not_blocked = list(set(not_blocked) - set(blocked))

    stats['mlbf_blocked_count'] = len(blocked)
    stats['mlbf_unblocked_count'] = len(not_blocked)

    fprs = [len(blocked) / (math.sqrt(2) * len(not_blocked)), 0.5]

    log.info("Generating filter")
    cascade = FilterCascade.cascade_with_characteristics(
        int(len(blocked) * 1.1), fprs)

    cascade.version = 1
    cascade.initialize(include=blocked, exclude=not_blocked)

    stats['mlbf_fprs'] = fprs
    stats['mlbf_version'] = cascade.version
    stats['mlbf_layers'] = cascade.layerCount()
    stats['mlbf_bits'] = cascade.bitCount()

    log.debug("Filter cascade layers: {layers}, bit: {bits}".format(
        layers=cascade.layerCount(), bits=cascade.bitCount()))

    cascade.check(entries=blocked, exclusions=not_blocked)
    return cascade


def legacy_publish_blocks(blocks):
    server = KintoServer(KINTO_BUCKET, KINTO_COLLECTION_LEGACY)
    for block in blocks:
        needs_updating = block.include_in_legacy and block.kinto_id
        needs_creating = block.include_in_legacy and not needs_updating
        needs_deleting = block.kinto_id and not block.include_in_legacy

        if needs_updating or needs_creating:
            if block.is_imported_from_kinto_regex:
                log.debug(
                    f'Block [{block.guid}] was imported from a regex guid so '
                    'can\'t be safely updated.  Creating as a new Block '
                    'instead.')
                needs_creating = True
            data = {
                'guid': block.guid,
                'details': {
                    'bug': block.url,
                    'why': block.reason,
                    'name': str(block.reason).partition('.')[0],  # required
                },
                'enabled': True,
                'versionRange': [{
                    'severity': 3,  # Always high severity now.
                    'minVersion': block.min_version,
                    'maxVersion': block.max_version,
                }],
            }
            if needs_creating:
                record = server.publish_record(data)
                block.update(kinto_id=record.get('id', ''))
            else:
                server.publish_record(data, block.kinto_id)
        elif needs_deleting:
            server.delete_record(block.kinto_id)
            block.update(kinto_id='')
        # else no existing kinto record and it shouldn't be in legacy so skip
    server.signoff_request()


def legacy_delete_blocks(blocks):
    server = KintoServer(KINTO_BUCKET, KINTO_COLLECTION_LEGACY)
    for block in blocks:
        if block.kinto_id and block.include_in_legacy:
            if block.is_imported_from_kinto_regex:
                log.debug(
                    f'Block [{block.guid}] was imported from a regex guid so '
                    'can\'t be safely deleted.  Skipping.')
            else:
                server.delete_record(block.kinto_id)
                block.update(kinto_id='')
    server.signoff_request()
