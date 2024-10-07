import json
import os
import secrets
from enum import Enum
from typing import List, Set, Tuple

from django.utils.functional import cached_property

from filtercascade import FilterCascade
from filtercascade.fileformats import HashAlgorithm

import olympia.core.logger
from olympia.amo.utils import SafeStorage
from olympia.blocklist.models import BlockVersion
from olympia.blocklist.utils import datetime_to_ts


log = olympia.core.logger.getLogger('z.amo.blocklist')


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


class MLBFDataType(Enum):
    # The names must match the values in BlockVersion.BLOCK_TYPE_CHOICES
    BLOCKED = 'blocked'
    # Extra name use for storing the "not blocked" items.
    NOT_BLOCKED = 'not_blocked'


def fetch_blocked_from_db(block_type: MLBFDataType):
    qs = BlockVersion.objects.filter(
        soft=BlockVersion.BLOCK_TYPE_CHOICES.for_constant(block_type.name).value,
        version__file__is_signed=True,
    ).values_list('block__guid', 'version__version', 'version_id', named=True)
    return list(qs)


def fetch_all_versions_from_db(excluding_version_ids=None):
    from olympia.versions.models import Version

    qs = Version.unfiltered.exclude(id__in=excluding_version_ids or ()).values_list(
        'addon__addonguid__guid', 'version'
    )
    return set(qs)


class BaseMLBFLoader:
    def __init__(self, storage: SafeStorage, _cache_path: str):
        self.storage = storage
        self._cache_path = _cache_path

    @cached_property
    def _raw(self):
        """
        raw serializable data for the given MLBFLoader.
        """
        return {key.value: self[key] for key in MLBFDataType}

    def __getitem__(self, key: MLBFDataType) -> List[str]:
        return getattr(self, f'{key.value}_items')

    @cached_property
    def cache_path(self):
        return self._file_path(name=self.CACHE_FILE, extension='json')

    @cached_property
    def blocked_items(self):
        raise NotImplementedError

    @cached_property
    def not_blocked_items(self):
        raise NotImplementedError


class MLBFStorageLoader(BaseMLBFLoader):
    def __init__(self, storage: SafeStorage, _cache_path: str):
        super().__init__(storage, _cache_path)
        with self.storage.open(self._cache_path, 'r') as f:
            self._data = json.load(f)

    @cached_property
    def blocked_items(self):
        return self._data.get(MLBFDataType.BLOCKED.value)

    @cached_property
    def not_blocked_items(self):
        return self._data.get(MLBFDataType.NOT_BLOCKED.value)


class MLBFDataBaseLoader(BaseMLBFLoader):
    def __init__(self, storage: SafeStorage, _cache_path: str):
        super().__init__(storage, _cache_path)
        self._version_excludes = []

        # TODO: there is an edge case where you create a new filter from
        # a previously used time stamp. THis could lead to invalid files
        # a filter using the DB should either clear the storage files
        # or raise to not allow reusing the same time stamp.
        # it is possibly debatable whether you should be able to
        # determine the created_at time as an argument at all

        # Save the raw data to storage to be used by later instances
        # of this filter.
        with self.storage.open(self._cache_path, 'w') as f:
            json.dump(self._raw, f)

    @cached_property
    def blocked_items(self):
        blocked = []

        for blocked_version in fetch_blocked_from_db(MLBFDataType.BLOCKED):
            blocked.append(
                (blocked_version.block__guid, blocked_version.version__version)
            )
            self._version_excludes.append(blocked_version.version_id)

        return MLBF.hash_filter_inputs(blocked)

    @cached_property
    def not_blocked_items(self):
        # see blocked_items - we need self._version_excludes populated
        blocked_items = self.blocked_items
        # even though we exclude all the version ids in the query there's an
        # edge case where the version string occurs twice for an addon so we
        # ensure not_blocked_items doesn't contain any blocked_items.
        return MLBF.hash_filter_inputs(
            fetch_all_versions_from_db(self._version_excludes) - set(blocked_items)
        )


class MLBF:
    CACHE_FILE = 'cache'
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
        self.data = data_class(storage=self.storage, _cache_path=self.cache_path)

    @classmethod
    def load_from_storage(cls, created_at: str = datetime_to_ts()):
        return cls(created_at, data_class=MLBFStorageLoader)

    @classmethod
    def generate_from_db(cls, created_at: str = datetime_to_ts()):
        return cls(created_at, data_class=MLBFDataBaseLoader)

    @classmethod
    def hash_filter_inputs(cls, input_list):
        """Returns a list"""
        return [
            cls.KEY_FORMAT.format(guid=guid, version=version)
            for (guid, version) in input_list
        ]

    def _file_path(
        self, name: str, data_type: MLBFDataType = None, extension: str = None
    ):
        if data_type is not None:
            name += f'-{data_type.value}'
            name += f'-{data_type.value}'
        if extension is not None:
            name += f'.{extension}'
        return self.storage.path(name)

    @cached_property
    def cache_path(self):
        return self._file_path(name=self.CACHE_FILE, extension='json')

    def filter_path(self, data_type: MLBFDataType):
        return self._file_path(name=self.FILTER_FILE, data_type=data_type)

    def stash_path(self, data_type: MLBFDataType):
        return self._file_path(
            name=self.STASH_FILE, data_type=data_type, extension='json'
        )

    def generate_and_write_filter(self, data_type: MLBFDataType):
        """
        Generate and write a new bloomfilter to storage.
        The filter will "block" versions which belong to
        the specified data_type and "not_block" all other versions.
        Not blocked items can include multiple data_types and does not
        strictly correspond to the "notblocked" items in the data store.
        """
        stats = {}

        filtered_versions = self.data[data_type]
        # TODO: should we actually include this in the diff/changed_count methods?
        unfiltered_versions = [
            item
            for key in MLBFDataType
            if key.value != data_type.value
            for item in self.data[key]
        ]

        bloomfilter = generate_mlbf(
            stats=stats, blocked=filtered_versions, not_blocked=unfiltered_versions
        )

        # write bloomfilter
        mlbf_path = self.filter_path(data_type)
        with self.storage.open(mlbf_path, 'wb') as filter_file:
            log.info(f'Writing to file {mlbf_path}')
            bloomfilter.tofile(filter_file)
            stats['mlbf_filesize'] = os.stat(mlbf_path).st_size

        log.info(json.dumps(stats))

        return bloomfilter

    def generate_diffs(
        self, data_type: MLBFDataType, previous_mlbf: 'MLBF' = None
    ) -> Tuple[Set[str], Set[str], int]:
        previous = set([] if previous_mlbf is None else previous_mlbf.data[data_type])
        current = set(self.data[data_type])
        extras = current - previous
        deletes = previous - current
        changed_count = (
            len(extras) + len(deletes) if len(previous) > 0 else len(current)
        )
        return extras, deletes, changed_count

    def blocks_changed_since_previous(
        self, data_type: MLBFDataType, previous_mlbf: 'MLBF' = None
    ):
        return self.generate_diffs(data_type, previous_mlbf)[2]

    def generate_and_write_stash(
        self, data_type: MLBFDataType, previous_mlbf: 'MLBF' = None
    ):
        # compare previous with current blocks
        extras, deletes, _ = self.generate_diffs(data_type, previous_mlbf)
        stash = {
            'blocked': list(extras),
            'unblocked': list(deletes),
        }
        # write stash
        stash_path = self.stash_path(data_type)
        with self.storage.open(stash_path, 'w') as json_file:
            log.info(f'Writing to file {stash_path}')
            json.dump(stash, json_file)
