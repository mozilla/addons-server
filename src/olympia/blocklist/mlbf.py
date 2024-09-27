import json
import os
import secrets
from collections import defaultdict
from typing import Dict, List, Set, Tuple

from django.utils.functional import cached_property

from filtercascade import FilterCascade
from filtercascade.fileformats import HashAlgorithm

import olympia.core.logger
from olympia.amo.utils import SafeStorage
from olympia.blocklist.models import BlockType
from olympia.constants.blocklist import BASE_REPLACE_THRESHOLD


log = olympia.core.logger.getLogger('z.amo.blocklist')


def generate_mlbf(stats, blocked, not_blocked):
    log.info('Starting to generating bloomfilter')

    cascade = FilterCascade(
        defaultHashAlg=HashAlgorithm.SHA256,
        salt=secrets.token_bytes(16),
    )

    error_rates = sorted((len(blocked), len(not_blocked)))
    cascade.set_crlite_error_rates(
        include_len=error_rates[0], exclude_len=error_rates[1]
    )

    stats['mlbf_blocked_count'] = len(blocked)
    stats['mlbf_notblocked_count'] = len(not_blocked)

    cascade.initialize(include=blocked, exclude=not_blocked)

    stats['mlbf_version'] = cascade.version
    stats['mlbf_layers'] = cascade.layerCount()
    stats['mlbf_bits'] = cascade.bitCount()

    log.info(
        f'Filter cascade layers: {cascade.layerCount()}, ' f'bit: {cascade.bitCount()}'
    )

    cascade.verify(include=blocked, exclude=not_blocked)
    return cascade


def fetch_blocked_from_db(block_type: BlockType):
    from olympia.blocklist.models import BlockVersion

    qs = BlockVersion.objects.by_block_type(block_type).values_list(
        'block__guid', 'version__version', 'version_id', named=True
    )
    all_versions = {
        block_version.version_id: (
            block_version.block__guid,
            block_version.version__version,
        )
        for block_version in qs
    }
    return all_versions


def fetch_all_versions_from_db(excluding_version_ids=None):
    from olympia.versions.models import Version

    qs = Version.unfiltered.exclude(id__in=excluding_version_ids or ()).values_list(
        'addon__addonguid__guid', 'version'
    )
    return list(qs)


class MLBFType(BlockType):
    NOTBLOCKED = 'notblocked'


class MLBF:
    KEY_FORMAT = '{guid}:{version}'

    def __init__(self, id_: str, previous_mlbf_: 'MLBF' = None):
        # simplify later code by assuming always a string
        self.id = str(id_)
        self.previous_mlbf = previous_mlbf_
        self.storage = SafeStorage(root_setting='MLBF_STORAGE_PATH')

    @classmethod
    def hash_filter_inputs(cls, input_list):
        """Returns a set"""
        return {
            cls.KEY_FORMAT.format(guid=guid, version=version)
            for (guid, version) in input_list
        }

    def _blocked_items(self) -> List[str]:
        raise NotImplementedError

    def _notblocked_items(self) -> List[str]:
        raise NotImplementedError

    def _load_json(self, name: str):
        path = self.storage.path(self.id, f'{name}.json')
        with self.storage.open(path, 'r') as json_file:
            return json.load(json_file)

    def _dump_json(self, name: str, data: any):
        path = self.storage.path(self.id, f'{name}.json')
        with self.storage.open(path, 'w') as json_file:
            log.info(f'Writing to file {path}')
            json.dump(data, json_file)

    @cached_property
    def data(self) -> Dict[MLBFType, List[str]]:
        data = defaultdict(list)

        for block_type, getter in {
            MLBFType.HARD: self._blocked_items,
            MLBFType.NOTBLOCKED: self._notblocked_items,
        }.items():
            results = getter()
            data[block_type] = results
            self._dump_json(results, block_type)

        return data

    # How to diff the current from the previous build of the bloom filter.
    # This will help us a) determine what blocks have changed since the last build
    # and b) if we need to generate a stash or a new base filter.
    @cached_property
    def diff(self) -> Dict[MLBFType, Tuple[Set[str], Set[str], int]]:
        diff = {}

        for block_type in self.data.keys():
            # Get the set of versions for the current and previous build
            previous = set(
                self.previous_mlbf.data[block_type] if self.previous_mlbf else []
            )
            current = set(self.data[block_type])
            # Determine which versions have been added or removed since the previous build
            extras = current - previous
            deletes = previous - current
            # Determine the number of changes for each block type
            changed_count = len(extras) + len(deletes)
            # Store the diff and count for each block type to independently
            # control filter/stash generation.
            diff[block_type] = (extras, deletes, changed_count)

        return diff

    # Generate and write a bloom filter with blocked and not blocked items of a given block type
    def _filter_path(self, block_type: MLBFType):
        return self.storage.path(self.id, f'filter-{block_type.value}.mlbf')

    def generate_and_write_filter(self, block_type: MLBFType):
        # Not blocked on a block type level includes any versions that are not in the
        # specified block type, not just the "unblocked" versions.
        not_blocked_types = [
            not_block_type
            for not_block_type in self.data.keys()
            if not_block_type != block_type
        ]

        blocked = self.data[block_type]
        not_blocked = [
            self.data[not_block_type] for not_block_type in not_blocked_types
        ]
        stats = {}

        bloomfilter = generate_mlbf(stats, blocked, not_blocked)

        # write bloomfilter
        mlbf_path = self._filter_path(block_type)
        with self.storage.open(mlbf_path, 'wb') as filter_file:
            log.info(f'Writing to file {mlbf_path}')
            bloomfilter.tofile(filter_file)
            stats['mlbf_filesize'] = os.stat(mlbf_path).st_size

        log.info(json.dumps(stats))

    def generate_and_write_stash(self, block_type: MLBFType):
        extras, deletes, _ = self.diff[block_type]

        stash = {
            'blocked': list(extras),
            'unblocked': list(deletes),
        }
        # write stash
        self._dump_json(f'{block_type.value}-stash', stash)
        return stash

    # The reset of the API now depends on which block type you want to work with.
    def should_reset_base_filter(self, block_type: MLBFType):
        extras, deletes = self.diff[block_type]
        return (len(extras) + len(deletes)) > BASE_REPLACE_THRESHOLD

    @classmethod
    def load_from_storage(cls, *args, **kwargs):
        return StoredMLBF(*args, **kwargs)

    @classmethod
    def generate_from_db(cls, *args, **kwargs):
        return DatabaseMLBF(*args, **kwargs)


class StoredMLBF(MLBF):
    def _blocked_items(self):
        return self._load_json(MLBFType.HARD)

    def _notblocked_items(self):
        return self._load_json(MLBFType.NOTBLOCKED)


class DatabaseMLBF(MLBF):
    @cached_property
    def _all_versions(self):
        return fetch_all_versions_from_db(self._version_excludes)

    def _blocked_items(self):
        blocked_ids_to_versions = fetch_blocked_from_db(BlockType.HARD)
        blocked = blocked_ids_to_versions.values()
        # cache version ids so query in not_blocked_items is efficient
        self._version_excludes = blocked_ids_to_versions.keys()
        return list(self.hash_filter_inputs(blocked))

    def _notblocked_items(self):
        # see blocked_items - we need self._version_excludes populated
        blocked_items = self._blocked_items()
        # even though we exclude all the version ids in the query there's an
        # edge case where the version string occurs twice for an addon so we
        # ensure not_blocked_items doesn't contain any blocked_items.
        return list(
            self.hash_filter_inputs(fetch_all_versions_from_db(self._version_excludes))
            - set(blocked_items)
        )
