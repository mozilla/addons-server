import json
import os
import secrets
from enum import Enum
from typing import List, Optional, Set, Tuple

from django.utils.functional import cached_property

from filtercascade import FilterCascade
from filtercascade.fileformats import HashAlgorithm

import olympia.core.logger
from olympia.amo.utils import SafeStorage
from olympia.blocklist.models import BlockType, BlockVersion
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
    HARD_BLOCKED = 'blocked'
    # SOFT_BLOCKED = 'soft_blocked'
    NOT_BLOCKED = 'not_blocked'


def fetch_blocked_from_db():
    qs = BlockVersion.objects.filter(
        version__file__is_signed=True, block_type=BlockType.BLOCKED
    ).values_list('block__guid', 'version__version', 'version_id', named=True)
    return set(qs)


def fetch_all_versions_from_db(excluding_version_ids=None):
    from olympia.versions.models import Version

    qs = Version.unfiltered.exclude(id__in=excluding_version_ids or ()).values_list(
        'addon__addonguid__guid', 'version'
    )
    return set(qs)


class BaseMLBFLoader:
    def __init__(self, storage: SafeStorage):
        self.storage = storage

    @cached_property
    def _raw(self):
        """
        raw serializable data for the given MLBFLoader.
        """
        return {key.value: self[key] for key in MLBFDataType}

    def __getitem__(self, key: MLBFDataType) -> List[str]:
        return getattr(self, f'{key.value}_items')

    @cached_property
    def _cache_path(self):
        return self.storage.path('cache.json')

    @cached_property
    def blocked_items(self) -> List[str]:
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
        return self._data.get(MLBFDataType.HARD_BLOCKED.value)

    @cached_property
    def not_blocked_items(self) -> List[str]:
        return self._data.get(MLBFDataType.NOT_BLOCKED.value)


class MLBFDataBaseLoader(BaseMLBFLoader):
    def __init__(self, storage: SafeStorage):
        super().__init__(storage)
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
    def blocked_items(self) -> List[str]:
        blocked = []

        for blocked_version in fetch_blocked_from_db():
            blocked.append(
                (blocked_version.block__guid, blocked_version.version__version)
            )
            self._version_excludes.append(blocked_version.version_id)

        return MLBF.hash_filter_inputs(blocked)

    @cached_property
    def not_blocked_items(self) -> List[str]:
        # see blocked_items - we need self._version_excludes populated
        blocked_items = self.blocked_items
        # even though we exclude all the version ids in the query there's an
        # edge case where the version string occurs twice for an addon so we
        # ensure not_blocked_items doesn't contain any blocked_items.
        return MLBF.hash_filter_inputs(
            fetch_all_versions_from_db(self._version_excludes) - set(blocked_items)
        )


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

    @property
    def filter_path(self):
        return self.storage.path('filter')

    @property
    def stash_path(self):
        return self.storage.path('stash.json')

    def generate_and_write_filter(self):
        stats = {}

        bloomfilter = generate_mlbf(
            stats=stats,
            blocked=self.data.blocked_items,
            not_blocked=self.data.not_blocked_items,
        )

        # write bloomfilter
        mlbf_path = self.filter_path
        with self.storage.open(mlbf_path, 'wb') as filter_file:
            log.info(f'Writing to file {mlbf_path}')
            bloomfilter.tofile(filter_file)
            stats['mlbf_filesize'] = os.stat(mlbf_path).st_size

        log.info(json.dumps(stats))

    def generate_diffs(
        self, previous_mlbf: 'MLBF' = None
    ) -> Tuple[Set[str], Set[str], int]:
        previous = set(
            [] if previous_mlbf is None else previous_mlbf.data.blocked_items
        )
        current = set(self.data.blocked_items)
        extras = current - previous
        deletes = previous - current
        changed_count = (
            len(extras) + len(deletes) if len(previous) > 0 else len(current)
        )
        return extras, deletes, changed_count

    def generate_and_write_stash(self, previous_mlbf: 'MLBF' = None):
        # compare previous with current blocks
        extras, deletes, _ = self.generate_diffs(previous_mlbf)
        stash_json = {
            'blocked': list(extras),
            'unblocked': list(deletes),
        }
        # write stash
        stash_path = self.stash_path
        with self.storage.open(stash_path, 'w') as json_file:
            log.info(f'Writing to file {stash_path}')
            json.dump(stash_json, json_file)

    def blocks_changed_since_previous(self, previous_mlbf: 'MLBF' = None):
        return self.generate_diffs(previous_mlbf)[2]

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
