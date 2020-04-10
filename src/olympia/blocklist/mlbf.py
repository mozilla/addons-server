import math
import secrets
from collections import defaultdict

from filtercascade import FilterCascade
from filtercascade.fileformats import HashAlgorithm

import olympia.core.logger


log = olympia.core.logger.getLogger('z.amo.blocklist')

MLBF_KEY_FORMAT = '{guid}:{version}'


def get_blocked_guids():
    from olympia.files.models import File
    from olympia.blocklist.models import Block

    blocks = Block.objects.all()
    blocks_guids = [block.guid for block in blocks]

    file_qs = File.objects.filter(
        version__addon__guid__in=blocks_guids,
        is_signed=True,
        is_webextension=True,
    ).order_by('version_id').values(
        'version__addon__guid',
        'version__version',
        'version_id')
    addons_versions = defaultdict(dict)
    for file_ in file_qs:
        addon_key = file_['version__addon__guid']
        addons_versions[addon_key][file_['version__version']] = (
            file_['version_id'])

    all_versions = {}
    # collect all the blocked versions
    for block in blocks:
        is_all_versions = (
            block.min_version == Block.MIN and
            block.max_version == Block.MAX)
        versions = {
            version_id: (block.guid, version)
            for version, version_id in addons_versions[block.guid].items()
            if is_all_versions or block.is_version_blocked(version)}
        all_versions.update(versions)
    return all_versions.values()


def get_all_guids():
    from olympia.versions.models import Version

    return Version.unfiltered.values_list('addon__guid', 'version')


def hash_filter_inputs(input_list):
    return [
        MLBF_KEY_FORMAT.format(guid=guid, version=version)
        for (guid, version) in input_list]


def generate_mlbf(stats, *, blocked=None, not_blocked=None):
    """Originally based on:
    https://github.com/mozilla/crlite/blob/master/create_filter_cascade/certs_to_crlite.py
    (not so much any longer, apart from the fprs calculation)
    """
    blocked = hash_filter_inputs(blocked or get_blocked_guids())
    not_blocked = hash_filter_inputs(not_blocked or get_all_guids())
    not_blocked = list(set(not_blocked) - set(blocked))

    salt = secrets.token_bytes(16)

    stats['mlbf_blocked_count'] = len(blocked)
    stats['mlbf_unblocked_count'] = len(not_blocked)

    fprs = [len(blocked) / (math.sqrt(2) * len(not_blocked)), 0.5]

    log.info("Generating filter")
    cascade = FilterCascade.cascade_with_characteristics(
        capacity=int(len(blocked) * 1.1),
        error_rates=fprs,
        defaultHashAlg=HashAlgorithm.SHA256,
        salt=salt,
    )
    cascade.initialize(include=blocked, exclude=not_blocked)

    stats['mlbf_fprs'] = fprs
    stats['mlbf_version'] = cascade.version
    stats['mlbf_layers'] = cascade.layerCount()
    stats['mlbf_bits'] = cascade.bitCount()

    log.debug("Filter cascade layers: {layers}, bit: {bits}".format(
        layers=cascade.layerCount(), bits=cascade.bitCount()))

    cascade.verify(include=blocked, exclude=not_blocked)
    return cascade
