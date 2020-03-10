import math
import secrets

from filtercascade import FilterCascade

import olympia.core.logger

log = olympia.core.logger.getLogger('z.amo.blocklist')


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

    return Version.unfiltered.values_list('addon__guid', 'version')


def hash_filter_inputs(input_list, key_format):
    return [
        key_format.format(guid=guid, version=version)
        for (guid, version) in input_list]


def get_mlbf_key_format(salt=None):
    salt = salt or secrets.token_hex(16)
    return '%s:{guid}:{version}' % salt


def generate_mlbf(stats, key_format, *, blocked=None, not_blocked=None):
    """Based on:
    https://github.com/mozilla/crlite/blob/master/create_filter_cascade/certs_to_crlite.py
    """
    blocked = hash_filter_inputs(
        blocked or get_blocked_guids(), key_format)
    not_blocked = hash_filter_inputs(
        not_blocked or get_all_guids(), key_format)

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
