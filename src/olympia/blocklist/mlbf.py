import json
import os
import secrets
from enum import Enum
from typing import Dict, List, Optional, Tuple

from django.utils.functional import cached_property

import waffle
from filtercascade import FilterCascade
from filtercascade.fileformats import HashAlgorithm

import olympia.core.logger
from olympia.amo.utils import SafeStorage
from olympia.blocklist.models import BlockType, BlockVersion
from olympia.blocklist.utils import datetime_to_ts
from olympia.constants.blocklist import BASE_REPLACE_THRESHOLD
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.amo.blocklist')


def ordered_diff_lists(
    previous: List[str], current: List[str]
) -> Tuple[List[str], List[str], int]:
    current_set = set(current)
    previous_set = set(previous)
    # Use lists instead of sets to maintain order
    extras = [x for x in current if x not in previous_set]
    deletes = [x for x in previous if x not in current_set]
    changed_count = len(extras) + len(deletes)
    return extras, deletes, changed_count


def generate_mlbf(stats, blocked, not_blocked):
    log.info('Starting to generating bloomfilter')

    cascade = FilterCascade(
        defaultHashAlg=HashAlgorithm.SHA256,
        salt=secrets.token_bytes(16),
    )

    len_blocked = len(blocked)
    len_unblocked = len(not_blocked)

    # We can only set error rates if both blocked and unblocked are non-empty
    if len_blocked > 0 and len_unblocked > 0:
        error_rates = sorted((len_blocked, len_unblocked))
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


# Extends the BlockType enum to include versions that have no block of any type
MLBFDataType = Enum(
    'MLBFDataType',
    [block_type.name for block_type in BlockType] + ['NOT_BLOCKED', 'not_blocked'],
    start=0,
)


class BaseMLBFLoader:
    def __init__(self, storage: SafeStorage):
        self.storage = storage

    @classmethod
    def data_type_key(cls, key: MLBFDataType) -> str:
        return key.name.lower()

    @cached_property
    def _raw(self):
        """
        raw serializable data for the given MLBFLoader.
        """
        return {self.data_type_key(key): self[key] for key in MLBFDataType}

    def __getitem__(self, key: MLBFDataType) -> List[str]:
        return getattr(self, f'{self.data_type_key(key)}_items')

    @cached_property
    def _cache_path(self):
        return self.storage.path('cache.json')

    @cached_property
    def blocked_items(self) -> List[str]:
        raise NotImplementedError

    @cached_property
    def soft_blocked_items(self) -> List[str]:
        raise NotImplementedError

    @cached_property
    def not_blocked_items(self) -> List[str]:
        raise NotImplementedError


class MLBFStorageLoader(BaseMLBFLoader):
    def __init__(self, storage: SafeStorage):
        super().__init__(storage)
        with self.storage.open(self._cache_path, 'r') as f:
            self._data = json.load(f)

    @cached_property
    def blocked_items(self) -> List[str]:
        return self._data.get(self.data_type_key(MLBFDataType.BLOCKED), [])

    @cached_property
    def soft_blocked_items(self) -> List[str]:
        return self._data.get(self.data_type_key(MLBFDataType.SOFT_BLOCKED), [])

    @cached_property
    def not_blocked_items(self) -> List[str]:
        return self._data.get(self.data_type_key(MLBFDataType.NOT_BLOCKED), [])


class MLBFDataBaseLoader(BaseMLBFLoader):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        with self.storage.open(self._cache_path, 'w') as f:
            json.dump(self._raw, f)

    @cached_property
    def _all_blocks(self):
        return (
            BlockVersion.objects.filter(version__file__is_signed=True)
            .distinct()
            .order_by('id')
            .values_list(
                'block__guid',
                'version__version',
                'version_id',
                'block_type',
                named=True,
            )
        )

    def _format_blocks(self, block_type: BlockType) -> List[str]:
        return MLBF.hash_filter_inputs(
            [
                (version.block__guid, version.version__version)
                for version in self._all_blocks
                if version.block_type == block_type
            ]
        )

    @cached_property
    def blocked_items(self) -> List[str]:
        return self._format_blocks(BlockType.BLOCKED)

    @cached_property
    def soft_blocked_items(self) -> List[str]:
        return self._format_blocks(BlockType.SOFT_BLOCKED)

    @cached_property
    def not_blocked_items(self) -> List[str]:
        all_blocks_ids = [version.version_id for version in self._all_blocks]
        not_blocked_items = MLBF.hash_filter_inputs(
            Version.unfiltered.exclude(id__in=all_blocks_ids or ())
            .distinct()
            .order_by('id')
            .values_list('addon__addonguid__guid', 'version')
        )
        blocked_items = set(self.blocked_items + self.soft_blocked_items)
        # even though we exclude all the version ids in the query there's an
        # edge case where the version string occurs twice for an addon so we
        # ensure not_blocked_items contain no blocked_items or soft_blocked_items.
        return [item for item in not_blocked_items if item not in blocked_items]


class MLBF:
    FILTER_FILE = 'filter'
    STASH_FILE = 'stash'
    KEY_FORMAT = '{guid}:{version}'

    def __init__(
        self,
        created_at: str = datetime_to_ts(),
        data_class: 'BaseMLBFLoader' = BaseMLBFLoader,
    ):
        self.created_at = created_at
        self.storage = SafeStorage(
            root_setting='MLBF_STORAGE_PATH',
            rel_location=str(self.created_at),
        )
        self.data: BaseMLBFLoader = data_class(storage=self.storage)

    @classmethod
    def hash_filter_inputs(cls, input_list):
        """Returns a list"""
        return [
            cls.KEY_FORMAT.format(guid=guid, version=version)
            for (guid, version) in input_list
        ]

    def filter_path(self, block_type: BlockType):
        # TODO: explain / test
        if block_type == BlockType.BLOCKED:
            return self.storage.path('filter')
        return self.storage.path(f'filter-{BaseMLBFLoader.data_type_key(block_type)}')

    @property
    def stash_path(self):
        return self.storage.path('stash.json')

    def delete(self):
        if self.storage.exists(self.storage.base_location):
            self.storage.rm_stored_dir(self.storage.base_location)
            log.info(f'Deleted {self.storage.base_location}')

    def generate_and_write_filter(self, block_type: BlockType = BlockType.BLOCKED):
        stats = {}

        bloomfilter = generate_mlbf(
            stats=stats,
            blocked=self.data.blocked_items,
            not_blocked=self.data.not_blocked_items,
        )

        # write bloomfilter
        mlbf_path = self.filter_path(block_type)
        with self.storage.open(mlbf_path, 'wb') as filter_file:
            log.info(f'Writing to file {mlbf_path}')
            bloomfilter.tofile(filter_file)
            stats['mlbf_filesize'] = os.stat(mlbf_path).st_size

        log.info(json.dumps(stats))

    def generate_diffs(
        self, previous_mlbf: 'MLBF' = None
    ) -> Dict[BlockType, Tuple[List[str], List[str], int]]:
        return {
            block_type: ordered_diff_lists(
                [] if previous_mlbf is None else previous_mlbf.data[block_type],
                self.data[block_type],
            )
            for block_type in BlockType
        }

    def generate_and_write_stash(self, previous_mlbf: 'MLBF' = None):
        """
        Generate and write the stash file representing changes between the
        previous and current bloom filters. See:
        https://bugzilla.mozilla.org/show_bug.cgi?id=soft-blocking

        In order to support Firefox clients that don't support soft blocking,
        unblocked is a union of deletions from blocked and deletions from
        soft_blocked, filtering out any versions that are in the newly blocked
        list.

        Versions that move from hard to soft blocked will be picked up by old
        clients as no longer hard blocked by being in the unblocked list.

        Clients supporting soft blocking will also see soft blocked versions as
        unblocked, but they won't unblocked them because the list of
        soft-blocked versions takes precedence over the list of unblocked
        versions.

        Versions that move from soft to hard blocked will be picked up by
        all clients in the blocked list. Note, even though the version is removed
        from the soft blocked list, it is important that we do not include it
        in the "unblocked" stash (like for hard blocked items) as this would
        result in the version being in both blocked and unblocked stashes.
        """
        diffs = self.generate_diffs(previous_mlbf)
        blocked_added, blocked_removed, _ = diffs[BlockType.BLOCKED]
        stash_json = {
            'blocked': blocked_added,
            'unblocked': blocked_removed,
        }

        if waffle.switch_is_active('enable-soft-blocking'):
            soft_blocked_added, soft_blocked_removed, _ = diffs[BlockType.SOFT_BLOCKED]
            stash_json['softblocked'] = soft_blocked_added
            stash_json['unblocked'] = [
                unblocked
                for unblocked in (blocked_removed + soft_blocked_removed)
                if unblocked not in blocked_added
            ]

        # write stash
        stash_path = self.stash_path
        with self.storage.open(stash_path, 'w') as json_file:
            log.info(f'Writing to file {stash_path}')
            json.dump(stash_json, json_file)
        return stash_json

    def blocks_changed_since_previous(
        self, block_type: BlockType = BlockType.BLOCKED, previous_mlbf: 'MLBF' = None
    ):
        _, _, changed_count = self.generate_diffs(previous_mlbf)[block_type]
        return changed_count

    def should_upload_filter(
        self, block_type: BlockType = BlockType.BLOCKED, previous_mlbf: 'MLBF' = None
    ):
        return (
            self.blocks_changed_since_previous(
                block_type=block_type, previous_mlbf=previous_mlbf
            )
            > BASE_REPLACE_THRESHOLD
        )

    def should_upload_stash(
        self, block_type: BlockType = BlockType.BLOCKED, previous_mlbf: 'MLBF' = None
    ):
        return (
            self.blocks_changed_since_previous(
                block_type=block_type, previous_mlbf=previous_mlbf
            )
            > 0
        )

    @classmethod
    def load_from_storage(
        cls, created_at: str = datetime_to_ts(), error_on_missing: bool = False
    ) -> Optional['MLBF']:
        try:
            return cls(created_at, data_class=MLBFStorageLoader)
        except FileNotFoundError:
            if error_on_missing:
                raise
            return None

    @classmethod
    def generate_from_db(cls, created_at: str = datetime_to_ts()):
        return cls(created_at, data_class=MLBFDataBaseLoader)
