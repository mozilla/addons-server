import json
import os
import secrets
from collections import defaultdict
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
from olympia.constants.blocklist import BASE_REPLACE_THRESHOLD_KEY
from olympia.versions.models import Version
from olympia.zadmin.models import get_config


log = olympia.core.logger.getLogger('z.amo.blocklist')


def get_base_replace_threshold():
    return get_config(BASE_REPLACE_THRESHOLD_KEY, int_value=True, default=5_000)


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


def generate_mlbf(stats, include, exclude):
    log.info('Starting to generating bloomfilter')

    cascade = FilterCascade(
        defaultHashAlg=HashAlgorithm.SHA256,
        salt=secrets.token_bytes(16),
    )

    len_include = len(include)
    len_exclude = len(exclude)

    # We can only set error rates if both include and exclude are non-empty
    if len_include > 0 and len_exclude > 0:
        error_rates = sorted((len_include, len_exclude))
        cascade.set_crlite_error_rates(
            include_len=error_rates[0], exclude_len=error_rates[1]
        )

    # TODO: https://github.com/mozilla/addons/issues/15204
    stats['mlbf_blocked_count'] = len(include)
    stats['mlbf_notblocked_count'] = len(exclude)

    cascade.initialize(include=include, exclude=exclude)

    stats['mlbf_version'] = cascade.version
    stats['mlbf_layers'] = cascade.layerCount()
    stats['mlbf_bits'] = cascade.bitCount()

    log.info(
        f'Filter cascade layers: {cascade.layerCount()}, ' f'bit: {cascade.bitCount()}'
    )

    cascade.verify(include=include, exclude=exclude)
    return cascade


# Extends the BlockType enum to include versions that have no block of any type
MLBFDataType = Enum(
    'MLBFDataType',
    [block_type.name for block_type in BlockType] + ['NOT_BLOCKED'],
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

    def _format_blocks(self, versions: List[Tuple[str, str]]) -> List[str]:
        unique_versions = set()
        deduped_versions = []

        for version in versions:
            if version not in unique_versions:
                unique_versions.add(version)
                deduped_versions.append(version)

        return MLBF.hash_filter_inputs(deduped_versions)

    @cached_property
    def blocked_items(self) -> List[str]:
        return self._format_blocks(
            [
                (version.block__guid, version.version__version)
                for version in self._all_blocks
                if version.block_type == BlockType.BLOCKED
            ]
        )

    @cached_property
    def soft_blocked_items(self) -> List[str]:
        return self._format_blocks(
            [
                (version.block__guid, version.version__version)
                for version in self._all_blocks
                if version.block_type == BlockType.SOFT_BLOCKED
            ]
        )

    @cached_property
    def not_blocked_items(self) -> List[str]:
        all_blocks_ids = [version.version_id for version in self._all_blocks]
        not_blocked_items = self._format_blocks(
            Version.unfiltered.exclude(id__in=all_blocks_ids)
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

    def filter_path(self, block_type: BlockType, compat: bool = False):
        # Override the return value of the BLOCKED filter
        # to for backwards compatibility with the old file name
        if block_type == BlockType.BLOCKED and compat:
            return self.storage.path('filter')
        return self.storage.path(f'filter-{BaseMLBFLoader.data_type_key(block_type)}')

    @property
    def stash_path(self):
        return self.storage.path('stash.json')

    def delete(self):
        if self.storage.exists(self.storage.base_location):
            self.storage.rm_stored_dir(self.storage.base_location)
            log.info(f'Deleted {self.storage.base_location}')

    def generate_and_write_filter(self, block_type: BlockType):
        """
        Generate and write the bloom filter for a given block type.
        Included items will be items in the specified block type list.
        Excluded items will be items in all other data types.

        We use the language of include and exclude to distinguish this concept
        from blocked and unblocked which are more specific to the block type.
        """
        stats = {}

        include_items = []
        exclude_items = []

        # Map over the data types in the MLBFDataType enum
        for data_type in MLBFDataType:
            # if the data type is in the specified block type,
            # add it to the include items
            if data_type.name == block_type.name:
                include_items = self.data[data_type]
            # otherwise add items to the exclude items
            else:
                exclude_items.extend(self.data[data_type])

        bloomfilter = generate_mlbf(
            stats=stats,
            include=include_items,
            exclude=exclude_items,
        )

        # write bloomfilter to old and new file names
        mlbf_path = self.filter_path(block_type, compat=True)
        with self.storage.open(mlbf_path, 'wb') as filter_file:
            log.info(f'Writing to file {mlbf_path}')
            bloomfilter.tofile(filter_file)
            stats['mlbf_filesize'] = os.stat(mlbf_path).st_size

        # also write to the new file name. After the switch is complete,
        # this file will be used and the old file will be deleted.
        mlbf_path = self.filter_path(block_type)
        with self.storage.open(mlbf_path, 'wb') as filter_file:
            log.info(f'Writing to file {mlbf_path}')
            bloomfilter.tofile(filter_file)
            stats['mlbf_filesize'] = os.stat(mlbf_path).st_size

        log.info(json.dumps(stats))
        return bloomfilter

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

    def generate_and_write_stash(
        self,
        previous_mlbf: 'MLBF' = None,
        blocked_base_filter: 'MLBF' = None,
        soft_blocked_base_filter: 'MLBF' = None,
    ):
        """
        Generate and write the stash file representing changes between the
        previous and current bloom filters. See:
        https://bugzilla.mozilla.org/show_bug.cgi?id=soft-blocking

        Since we might be generating both a filter and a stash at the exact same time,
        we need to compute a stash that doesn't include the data already in the newly
        created filter.

        Items that are removed from one block type and added to another are
        excluded from the unblocked list to prevent double counting.

        If a block type needs a new filter, we do not include any items for that
        block type in the stash to prevent double counting items.

        We used to generate a list of `unblocked` versions as a union of deletions
        from blocked and deletions from soft_blocked, filtering out any versions
        that are in the newly blocked list in order to support Firefox clients that
        don't support soft blocking. That, unfortunately, caused other issues so
        currently we are very conservative, and we do not fully support old clients.
        See: https://github.com/mozilla/addons/issues/15208
        """
        # Map block types to hard coded stash keys for compatibility
        # with the expected keys in remote settings.
        STASH_KEYS = {
            BlockType.BLOCKED: 'blocked',
            BlockType.SOFT_BLOCKED: 'softblocked',
        }
        UNBLOCKED_STASH_KEY = 'unblocked'

        # Base stash includes all of the expected keys from STASH_KEYS + unblocked
        stash_json = {key: [] for key in [UNBLOCKED_STASH_KEY, *STASH_KEYS.values()]}

        diffs = self.generate_diffs(previous_mlbf)
        blocked_added, blocked_removed, _ = diffs[BlockType.BLOCKED]
        added_items = set(blocked_added)

        if not self.should_upload_filter(BlockType.BLOCKED, blocked_base_filter):
            stash_json[STASH_KEYS[BlockType.BLOCKED]] = blocked_added
            stash_json[UNBLOCKED_STASH_KEY] = blocked_removed

        if waffle.switch_is_active('enable-soft-blocking'):
            soft_blocked_added, soft_blocked_removed, _ = diffs[BlockType.SOFT_BLOCKED]
            added_items.update(soft_blocked_added)
            if not self.should_upload_filter(
                BlockType.SOFT_BLOCKED, soft_blocked_base_filter
            ):
                stash_json[STASH_KEYS[BlockType.SOFT_BLOCKED]] = soft_blocked_added
                stash_json[UNBLOCKED_STASH_KEY].extend(soft_blocked_removed)

        # Remove any items that were added to a block type.
        stash_json[UNBLOCKED_STASH_KEY] = [
            item for item in stash_json[UNBLOCKED_STASH_KEY] if item not in added_items
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
            > get_base_replace_threshold()
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

    def validate(self):
        store = defaultdict(lambda: defaultdict(int))

        # Create a map of each guid:version string in the cache.json
        # and the set of data types that contain it and the count of
        # how many times it occurs in each data type.
        for key in MLBFDataType:
            for item in self.data[key]:
                store[item][key] += 1

        # Verify that each item occurs only one time and in only one data type
        for item, data_types in store.items():
            # We expect each item to only occur in one data type
            if len(data_types) > 1:
                formatted_data_types = ', '.join(key.name for key in data_types.keys())
                raise ValueError(
                    f'Item {item} found in multiple data types: {formatted_data_types}'
                )
            # We expect each item to occur only one time in a given data type
            for dtype, count in data_types.items():
                if count > 1:
                    raise ValueError(
                        f'Item {item} found {count} times in data type ' f'{dtype.name}'
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
