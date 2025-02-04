import json
from functools import cached_property
from unittest import mock

from olympia import amo
from olympia.addons.models import GUID_REUSE_FORMAT
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    block_factory,
    user_factory,
    version_factory,
)
from olympia.amo.utils import SafeStorage
from olympia.blocklist.models import BlockType, BlockVersion

from ..mlbf import (
    MLBF,
    BaseMLBFLoader,
    MLBFDataBaseLoader,
    MLBFDataType,
    MLBFStorageLoader,
    ordered_diff_lists,
)


class _MLBFBase(TestCase):
    def setUp(self):
        self.storage = SafeStorage()
        self.user = user_factory()

    def _blocked_addon(self, block_type=BlockType.BLOCKED, **kwargs):
        addon = addon_factory(**kwargs)
        block = block_factory(
            guid=addon.guid, updated_by=self.user, block_type=block_type
        )
        return addon, block

    def _version(self, addon, is_signed=True):
        return version_factory(addon=addon, file_kw={'is_signed': is_signed})

    def _block_version(self, block, version, block_type=BlockType.BLOCKED):
        return BlockVersion.objects.create(
            block=block,
            version=version,
            block_type=block_type,
        )


class TestOrderedDiffLists(TestCase):
    def test_return_added(self):
        assert ordered_diff_lists(['a', 'b'], ['a', 'b', 'c']) == (['c'], [], 1)

    def test_return_removed(self):
        assert ordered_diff_lists(['a', 'b', 'c'], ['a', 'b']) == ([], ['c'], 1)

    def test_return_added_and_removed(self):
        assert ordered_diff_lists(['a', 'b', 'c'], ['b', 'c', 'd']) == (['d'], ['a'], 2)

    def test_large_diff(self):
        size = 2_000_000
        even_items = [i for i in range(size) if i % 2 == 0]
        odd_items = [i for i in range(size) if i % 2 == 1]
        assert ordered_diff_lists(even_items, odd_items) == (
            odd_items,
            even_items,
            size,
        )


class TestBaseMLBFLoader(_MLBFBase):
    class TestStaticLoader(BaseMLBFLoader):
        @cached_property
        def blocked_items(self):
            return ['blocked:version']

        @cached_property
        def soft_blocked_items(self):
            return ['softblocked:version']

        @cached_property
        def not_blocked_items(self):
            return ['notblocked:version']

    def test_missing_methods_raises(self):
        with self.assertRaises(NotImplementedError):
            _ = BaseMLBFLoader(self.storage)._raw

        class TestMissingNotBlocked(BaseMLBFLoader):
            @cached_property
            def blocked_items(self):
                return []

        with self.assertRaises(NotImplementedError):
            _ = TestMissingNotBlocked(self.storage).not_blocked_items

        class TestMissingBlocked(BaseMLBFLoader):
            @cached_property
            def notblocked_items(self):
                return []

        with self.assertRaises(NotImplementedError):
            _ = TestMissingBlocked(self.storage).blocked_items

    def test_raw_contains_correct_data(self):
        loader = self.TestStaticLoader(self.storage)
        assert loader._raw == {
            'blocked': ['blocked:version'],
            'soft_blocked': ['softblocked:version'],
            'not_blocked': ['notblocked:version'],
        }

    def test_invalid_key_access_raises(self):
        loader = self.TestStaticLoader(self.storage)

        with self.assertRaises(AttributeError):
            loader['invalid']
        with self.assertRaises(AttributeError):
            loader[BlockType.BANANA]

    def test_valid_key_access_returns_expected_data(self):
        loader = self.TestStaticLoader(self.storage)
        assert loader[MLBFDataType.BLOCKED] == ['blocked:version']
        assert loader[MLBFDataType.NOT_BLOCKED] == ['notblocked:version']

    def test_cache_raw_data(self):
        loader = self.TestStaticLoader(self.storage)

        for data_type in MLBFDataType:
            assert loader[data_type] == loader._raw[loader.data_type_key(data_type)]

        # The source of truth should ultimately be the named cached properties
        # Even though _raw is cached, it should still return
        # the reference to the named property
        loader.blocked_items = []
        assert loader[MLBFDataType.BLOCKED] == []

    def test_contains_only_valid_keys(self):
        loader = self.TestStaticLoader(self.storage)

        loader_keys = list(loader._raw.keys())
        data_type_keys = [BaseMLBFLoader.data_type_key(key) for key in MLBFDataType]

        assert sorted(loader_keys) == sorted(data_type_keys)


class TestMLBFStorageLoader(_MLBFBase):
    def setUp(self):
        super().setUp()
        self._data = {
            'blocked': ['blocked:version'],
            'not_blocked': ['notblocked:version'],
            'soft_blocked': ['softblocked:version'],
        }

    def test_raises_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            _ = MLBFStorageLoader(self.storage)._raw

    def test_loads_data_from_file(self):
        with self.storage.open('cache.json', 'w') as f:
            json.dump(self._data, f)

        loader = MLBFStorageLoader(self.storage)
        assert loader._raw == self._data

    def test_fallback_to_empty_list_for_missing_key(self):
        for key in self._data.keys():
            new_data = self._data.copy()
            new_data.pop(key)
            # Generate a corrupted `cache.json` file
            # (we do this for each key).
            with self.storage.open('cache.json', 'w') as f:
                json.dump(new_data, f)
            loader = MLBFStorageLoader(self.storage)
            assert loader._raw == {**new_data, key: []}


class TestMLBFDataBaseLoader(_MLBFBase):
    def test_load_returns_expected_data(self):
        """
        Test that the class returns a dictionary mapping the
        expected TestMLBFDataBaseLoader keys to the blocked and notblocked item lists.
        """
        addon, block = self._blocked_addon()

        notblocked_version = addon.current_version
        second_notblocked_version = self._version(addon)
        blocked_versions = []
        blocked_hashes = []
        soft_blocked_versions = []
        soft_blocked_hashes = []

        for _ in range(10):
            # Create a blocked version with hashed guid:version
            block_version = self._block_version(
                block, self._version(addon), block_type=BlockType.BLOCKED
            )
            blocked_versions.append(block_version)
            blocked_hashes.append(
                (block_version.block.guid, block_version.version.version)
            )

            # Create a soft blocked version with hashed guid:version
            soft_blocked_version = self._block_version(
                block, self._version(addon), block_type=BlockType.SOFT_BLOCKED
            )
            soft_blocked_versions.append(soft_blocked_version)
            soft_blocked_hashes.append(
                (soft_blocked_version.block.guid, soft_blocked_version.version.version)
            )

        mlbf_data = MLBFDataBaseLoader(self.storage)

        assert mlbf_data[MLBFDataType.BLOCKED] == MLBF.hash_filter_inputs(
            blocked_hashes
        )
        assert mlbf_data[MLBFDataType.SOFT_BLOCKED] == MLBF.hash_filter_inputs(
            soft_blocked_hashes
        )
        assert mlbf_data[MLBFDataType.NOT_BLOCKED] == MLBF.hash_filter_inputs(
            [
                (notblocked_version.addon.guid, notblocked_version.version),
                (
                    second_notblocked_version.addon.guid,
                    second_notblocked_version.version,
                ),
            ]
        )

    def test_blocked_items_caches_excluded_version_ids(self):
        """
        Test that accessing the blocked_items property caches the version IDs
        to exclude in the notblocked_items property.
        """
        addon, block = self._blocked_addon()
        not_blocked_version = addon.current_version
        hard_blocked = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        soft_block = self._block_version(
            block, self._version(addon), block_type=BlockType.SOFT_BLOCKED
        )
        with self.assertNumQueries(2):
            mlbf_data = MLBFDataBaseLoader(self.storage)

        assert mlbf_data.blocked_items == MLBF.hash_filter_inputs(
            [(hard_blocked.block.guid, hard_blocked.version.version)]
        )
        assert mlbf_data.soft_blocked_items == MLBF.hash_filter_inputs(
            [(soft_block.block.guid, soft_block.version.version)]
        )
        assert mlbf_data.not_blocked_items == MLBF.hash_filter_inputs(
            [(not_blocked_version.addon.guid, not_blocked_version.version)]
        )

    def test_hash_filter_inputs_returns_set_of_hashed_strings(self):
        """
        Test that the hash_filter_inputs class method returns a set of
        hashed guid:version strings given an input list of (guid, version)
        tuples.
        """
        default = MLBF.hash_filter_inputs(
            [
                ('guid', 'version'),
            ]
        )
        assert default == ['guid:version']

    def _test_reused_guids_are_deduped(self, block_type=None):
        addon_args = {
            'guid': 'dupe@me',
            'version_kw': {'version': '1.0'},
            'file_kw': {'is_signed': True},
        }
        if block_type is not None:
            addon, _ = self._blocked_addon(
                block_type=block_type,
                **addon_args,
            )
        else:
            addon = addon_factory(**addon_args)
        addon2 = addon_factory(version_kw={'version': '1.0'})
        addon2.addonguid.update(guid=addon.guid)

        mlbf_data = MLBFDataBaseLoader(self.storage)

        for key, value in mlbf_data._raw.items():
            # For the selected block type, we expect a single deduped guid:version
            # For the other block types, we expect an empty list
            if key == (
                MLBFDataBaseLoader.data_type_key(block_type)
                if block_type is not None
                else 'not_blocked'
            ):
                assert value == MLBF.hash_filter_inputs(
                    [
                        (addon.guid, addon.current_version.version),
                    ]
                )
            else:
                assert value == []

    def test_reused_guids_deduped_not_blocked(self):
        """
        Test that duplicate guids are deduped in the not_blocked_items list.
        """
        self._test_reused_guids_are_deduped(block_type=None)

    def test_reused_guids_deduped_blocked(self):
        """
        Test that duplicate guids are deduped in the blocked_items list.
        """
        self._test_reused_guids_are_deduped(block_type=BlockType.BLOCKED)

    def test_reused_guids_deduped_soft_blocked(self):
        """
        Test that duplicate guids are deduped in the soft_blocked_items list.
        """
        self._test_reused_guids_are_deduped(block_type=BlockType.SOFT_BLOCKED)


class TestMLBF(_MLBFBase):
    def test_filter_path(self):
        mlbf = MLBF.generate_from_db('test')
        assert mlbf.filter_path(BlockType.BLOCKED, compat=True).endswith('filter')
        assert mlbf.filter_path(BlockType.BLOCKED).endswith('filter-blocked')
        assert mlbf.filter_path(BlockType.SOFT_BLOCKED).endswith('filter-soft_blocked')

    def test_save_filter_writes_to_both_file_names(self):
        mlbf = MLBF.generate_from_db('test')
        mlbf.generate_and_write_filter(BlockType.BLOCKED)
        assert mlbf.storage.exists('filter')
        assert mlbf.storage.exists('filter-blocked')

    def test_get_data_from_db(self):
        self._blocked_addon()
        mlbf = MLBF.generate_from_db('test')
        assert isinstance(mlbf.data, MLBFDataBaseLoader)
        mlbf_data = MLBFDataBaseLoader(mlbf.storage)
        assert mlbf.data._raw == mlbf_data._raw

    def test_cache_json_is_sorted(self):
        addon, block = self._blocked_addon()

        notblocked_version = addon.current_version
        second_notblocked_version = self._version(addon)

        blocked_versions = []
        blocked_hashes = []
        soft_blocked_versions = []
        soft_blocked_hashes = []

        for _ in range(10):
            blocked_version = self._block_version(
                block, self._version(addon), block_type=BlockType.BLOCKED
            )
            blocked_versions.append(blocked_version)
            blocked_hashes.append(
                (blocked_version.block.guid, blocked_version.version.version)
            )
            soft_blocked_version = self._block_version(
                block, self._version(addon), block_type=BlockType.SOFT_BLOCKED
            )
            soft_blocked_versions.append(soft_blocked_version)
            soft_blocked_hashes.append(
                (soft_blocked_version.block.guid, soft_blocked_version.version.version)
            )

        mlbf = MLBF.generate_from_db('test')
        with mlbf.storage.open(mlbf.data._cache_path, 'r') as f:
            assert json.load(f) == {
                'blocked': MLBF.hash_filter_inputs(blocked_hashes),
                'soft_blocked': MLBF.hash_filter_inputs(soft_blocked_hashes),
                'not_blocked': MLBF.hash_filter_inputs(
                    [
                        (notblocked_version.addon.guid, notblocked_version.version),
                        (
                            second_notblocked_version.addon.guid,
                            second_notblocked_version.version,
                        ),
                    ]
                ),
            }

    def test_load_from_storage_returns_data_from_storage(self):
        self._blocked_addon()
        mlbf = MLBF.generate_from_db('test')
        cached_mlbf = MLBF.load_from_storage('test')
        assert isinstance(cached_mlbf.data, MLBFStorageLoader)
        assert mlbf.data._raw == cached_mlbf.data._raw

    def test_load_from_storage_raises_if_missing(self):
        MLBF.load_from_storage('test', error_on_missing=False)
        with self.assertRaises(FileNotFoundError):
            MLBF.load_from_storage('test', error_on_missing=True)

    def test_diff_returns_stateless_without_previous(self):
        """
        Starting with an initially blocked addon, diff after removing the block
        depends on whether a previous mlbf is provided and if that previous mlbf
        has the unblocked addon already
        """
        addon, _ = self._blocked_addon(file_kw={'is_signed': True})
        base_mlbf = MLBF.generate_from_db('base')

        stateless_diff = {
            BlockType.BLOCKED: (
                MLBF.hash_filter_inputs(
                    [(addon.block.guid, addon.current_version.version)]
                ),
                [],
                1,
            ),
            BlockType.SOFT_BLOCKED: ([], [], 0),
        }

        assert base_mlbf.generate_diffs() == stateless_diff

        next_mlbf = MLBF.generate_from_db('next')
        # If we don't include the base_mlbf, unblocked version will still be in the diff
        assert next_mlbf.generate_diffs() == stateless_diff
        # Providing a previous mlbf with the unblocked version already included
        # removes it from the diff
        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == {
            BlockType.BLOCKED: ([], [], 0),
            BlockType.SOFT_BLOCKED: ([], [], 0),
        }

    def test_diff_no_changes(self):
        addon, block = self._blocked_addon()
        self._block_version(block, self._version(addon), block_type=BlockType.BLOCKED)
        base_mlbf = MLBF.generate_from_db('test')
        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == {
            BlockType.BLOCKED: ([], [], 0),
            BlockType.SOFT_BLOCKED: ([], [], 0),
        }
        assert next_mlbf.generate_and_write_stash(previous_mlbf=base_mlbf) == {
            'blocked': [],
            'softblocked': [],
            'unblocked': [],
        }

    def test_block_added(self):
        addon, block = self._blocked_addon()
        base_mlbf = MLBF.generate_from_db('test')

        new_block = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        (new_block_hash,) = MLBF.hash_filter_inputs(
            [(new_block.block.guid, new_block.version.version)]
        )
        new_soft_block = self._block_version(
            block, self._version(addon), block_type=BlockType.SOFT_BLOCKED
        )
        (new_soft_block_hash,) = MLBF.hash_filter_inputs(
            [(new_soft_block.block.guid, new_soft_block.version.version)]
        )

        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == {
            BlockType.BLOCKED: (
                [new_block_hash],
                [],
                1,
            ),
            BlockType.SOFT_BLOCKED: ([new_soft_block_hash], [], 1),
        }
        assert next_mlbf.generate_and_write_stash(previous_mlbf=base_mlbf) == {
            'blocked': [new_block_hash],
            'softblocked': [new_soft_block_hash],
            'unblocked': [],
        }

    def test_block_removed(self):
        addon, block = self._blocked_addon()
        block_version = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        (block_hash,) = MLBF.hash_filter_inputs(
            [(block_version.block.guid, block_version.version.version)]
        )
        base_mlbf = MLBF.generate_from_db('test')
        block_version.delete()
        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == {
            BlockType.BLOCKED: (
                [],
                [block_hash],
                1,
            ),
            BlockType.SOFT_BLOCKED: ([], [], 0),
        }
        assert next_mlbf.generate_and_write_stash(previous_mlbf=base_mlbf) == {
            'blocked': [],
            'softblocked': [],
            'unblocked': [block_hash],
        }

    def test_block_added_and_removed(self):
        addon, block = self._blocked_addon()
        block_version = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        (block_hash,) = MLBF.hash_filter_inputs(
            [(block_version.block.guid, block_version.version.version)]
        )
        base_mlbf = MLBF.generate_from_db('test')

        new_block = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        (new_block_hash,) = MLBF.hash_filter_inputs(
            [(new_block.block.guid, new_block.version.version)]
        )
        block_version.delete()

        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == {
            BlockType.BLOCKED: (
                [new_block_hash],
                [block_hash],
                2,
            ),
            BlockType.SOFT_BLOCKED: ([], [], 0),
        }
        assert next_mlbf.generate_and_write_stash(previous_mlbf=base_mlbf) == {
            'blocked': [new_block_hash],
            'softblocked': [],
            'unblocked': [block_hash],
        }

    def test_block_hard_to_soft(self):
        addon, block = self._blocked_addon()
        block_version = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        (block_hash,) = MLBF.hash_filter_inputs(
            [(block_version.block.guid, block_version.version.version)]
        )
        base_mlbf = MLBF.generate_from_db('test')
        block_version.update(block_type=BlockType.SOFT_BLOCKED)
        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == {
            BlockType.BLOCKED: (
                [],
                [block_hash],
                1,
            ),
            BlockType.SOFT_BLOCKED: (
                [block_hash],
                [],
                1,
            ),
        }
        assert next_mlbf.generate_and_write_stash(previous_mlbf=base_mlbf) == {
            'blocked': [],
            'softblocked': [block_hash],
            'unblocked': [],
        }

    def test_block_soft_to_hard(self):
        addon, block = self._blocked_addon()
        block_version = self._block_version(
            block, self._version(addon), block_type=BlockType.SOFT_BLOCKED
        )
        (block_hash,) = MLBF.hash_filter_inputs(
            [(block_version.block.guid, block_version.version.version)]
        )
        base_mlbf = MLBF.generate_from_db('test')
        block_version.update(block_type=BlockType.BLOCKED)
        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == {
            BlockType.BLOCKED: (
                [block_hash],
                [],
                1,
            ),
            BlockType.SOFT_BLOCKED: (
                [],
                [block_hash],
                1,
            ),
        }
        assert next_mlbf.generate_and_write_stash(previous_mlbf=base_mlbf) == {
            'blocked': [block_hash],
            'softblocked': [],
            'unblocked': [],
        }

    @mock.patch('olympia.blocklist.mlbf.get_base_replace_threshold')
    def test_hard_to_soft_multiple(self, mock_get_base_replace_threshold):
        mock_get_base_replace_threshold.return_value = 2
        addon, block = self._blocked_addon()
        block_versions = [
            self._block_version(block, self._version(addon)) for _ in range(2)
        ]
        block_hashes = MLBF.hash_filter_inputs(
            [
                (block_version.block.guid, block_version.version.version)
                for block_version in block_versions
            ]
        )
        base_mlbf = MLBF.generate_from_db('test')

        for block_version in block_versions:
            block_version.update(block_type=BlockType.SOFT_BLOCKED)

        next_mlbf = MLBF.generate_from_db('test_two')

        assert not next_mlbf.should_upload_filter(BlockType.SOFT_BLOCKED, base_mlbf)

        assert next_mlbf.generate_and_write_stash(previous_mlbf=base_mlbf) == {
            'blocked': [],
            'softblocked': block_hashes,
            'unblocked': [],
        }

    @mock.patch('olympia.blocklist.mlbf.get_base_replace_threshold')
    def test_stash_is_empty_if_uploading_new_filter(
        self, mock_get_base_replace_threshold
    ):
        mock_get_base_replace_threshold.return_value = 1
        mlbf = MLBF.generate_from_db('test')

        # No changes yet so no new filter and empty stash
        assert not mlbf.should_upload_filter(BlockType.BLOCKED)
        assert mlbf.generate_and_write_stash() == {
            'blocked': [],
            'softblocked': [],
            'unblocked': [],
        }

        # One of each version produces a stash
        addon, block = self._blocked_addon()
        hard_block = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        soft_block = self._block_version(
            block, self._version(addon), block_type=BlockType.SOFT_BLOCKED
        )
        hard_stash, soft_stash = MLBF.hash_filter_inputs(
            [
                (hard_block.block.guid, hard_block.version.version),
                (soft_block.block.guid, soft_block.version.version),
            ]
        )

        next_mlbf = MLBF.generate_from_db('test_two')
        # No new filter yet
        assert not next_mlbf.should_upload_filter(BlockType.BLOCKED, mlbf)

        assert next_mlbf.generate_and_write_stash(mlbf) == {
            'blocked': [hard_stash],
            'softblocked': [soft_stash],
            'unblocked': [],
        }

        # Harden the soft blocked version
        soft_block.update(block_type=BlockType.BLOCKED)
        final_mlbf = MLBF.generate_from_db('test_three')

        # When comparing to the base filter, the stash is empty
        assert final_mlbf.generate_and_write_stash(
            previous_mlbf=next_mlbf,
            blocked_base_filter=mlbf,
            soft_blocked_base_filter=None,
        ) == {
            'blocked': [],
            'softblocked': [],
            'unblocked': [],
        }

        # When comparing to the previous mlbf,
        # the stash includes the hard blocked version
        assert final_mlbf.generate_and_write_stash(
            previous_mlbf=next_mlbf,
            blocked_base_filter=next_mlbf,
            soft_blocked_base_filter=None,
        ) == {
            'blocked': [soft_stash],
            'softblocked': [],
            'unblocked': [],
        }

    def test_diff_invalid_cache(self):
        addon, block = self._blocked_addon(file_kw={'is_signed': True})
        soft_blocked = self._block_version(
            block, self._version(addon), block_type=BlockType.SOFT_BLOCKED
        )
        base = MLBF.generate_from_db()
        # Overwrite the cache file removing the soft blocked version
        with base.storage.open(base.data._cache_path, 'r+') as f:
            data = json.load(f)
            del data['soft_blocked']
            f.seek(0)
            json.dump(data, f)
            f.truncate()

        previous_mlbf = MLBF.load_from_storage(base.created_at)

        mlbf = MLBF.generate_from_db()

        # The diff should include the soft blocked version because it was removed
        # and should not include the blocked version because it was not changed
        assert mlbf.generate_diffs(previous_mlbf=previous_mlbf) == {
            BlockType.BLOCKED: ([], [], 0),
            BlockType.SOFT_BLOCKED: (
                MLBF.hash_filter_inputs(
                    [(soft_blocked.block.guid, soft_blocked.version.version)]
                ),
                [],
                1,
            ),
        }

    def test_diff_all_possible_changes(self):
        """
        Simulates 6 guid:version combinations moving from one state to another
        covering all possible movements and the final diff state.

        1. Not blocked -> Soft blocked
        2. Not blocked -> Blocked
        3. Soft blocked -> Blocked
        4. Soft blocked -> Not blocked
        5. Blocked -> Soft blocked
        6. Blocked -> Not blocked

        """
        # Create a version that isn't blocked yet.
        one = addon_factory(guid='1', file_kw={'is_signed': True})
        (one_hash,) = MLBF.hash_filter_inputs([(one.guid, one.current_version.version)])
        # Create a second version not blocked yet.
        two = addon_factory(guid='2', file_kw={'is_signed': True})
        (two_hash,) = MLBF.hash_filter_inputs([(two.guid, two.current_version.version)])
        # Create a soft blocked version.
        three, three_block = self._blocked_addon(
            guid='3', block_type=BlockType.SOFT_BLOCKED, file_kw={'is_signed': True}
        )
        (three_hash,) = MLBF.hash_filter_inputs(
            [(three.guid, three.current_version.version)]
        )
        # Create another soft blocked version.
        four, four_block = self._blocked_addon(
            guid='4', block_type=BlockType.SOFT_BLOCKED, file_kw={'is_signed': True}
        )
        (four_hash,) = MLBF.hash_filter_inputs(
            [(four.guid, four.current_version.version)]
        )
        # Create a hard blocked version.
        five, five_block = self._blocked_addon(
            guid='5', block_type=BlockType.BLOCKED, file_kw={'is_signed': True}
        )
        (five_hash,) = MLBF.hash_filter_inputs(
            [(five.guid, five.current_version.version)]
        )
        # And finally, create another hard blocked version.
        six, six_block = self._blocked_addon(
            guid='6', block_type=BlockType.BLOCKED, file_kw={'is_signed': True}
        )
        (six_hash,) = MLBF.hash_filter_inputs([(six.guid, six.current_version.version)])

        # At this point, we have 2 versions not blocked,
        # and 4 versions blocked. We're going
        # to generate a first MLBF from that set of versions.
        first_mlbf = MLBF.generate_from_db('first')

        # We expect the 4 blocked versions to be in the diff, sorted by block type.
        assert first_mlbf.generate_diffs() == {
            BlockType.BLOCKED: ([five_hash, six_hash], [], 2),
            BlockType.SOFT_BLOCKED: ([three_hash, four_hash], [], 2),
        }

        assert first_mlbf.generate_and_write_stash() == {
            'blocked': [five_hash, six_hash],
            'softblocked': [three_hash, four_hash],
            'unblocked': [],
        }

        # Update the existing blocks, and create new ones for
        # the versions "one" and "two".

        # The first version gets soft blocked now.
        block_factory(
            guid=one.guid, updated_by=self.user, block_type=BlockType.SOFT_BLOCKED
        )
        # The second version is hard blocked.
        block_factory(guid=two.guid, updated_by=self.user, block_type=BlockType.BLOCKED)
        # 3 was soft-blocked and is now hard blocked.
        three_block.blockversion_set.first().update(block_type=BlockType.BLOCKED)
        # 4 was soft blocked and is now unblocked.
        four_block.delete()
        # 5 was hard blocked and is now soft blocked.
        five_block.blockversion_set.first().update(block_type=BlockType.SOFT_BLOCKED)
        # 6 was hard blocked and is now unblocked.
        six_block.delete()

        # We regenerate another MLBF based on the updates we've just done
        # to verify the final state of each version.
        second_mlbf = MLBF.generate_from_db('second')

        # The order is based on the ID (i.e. creation time) of the block,
        # not the version so we expect two after three since two was
        # blocked after three.
        assert second_mlbf.generate_diffs(previous_mlbf=first_mlbf) == {
            BlockType.BLOCKED: (
                [three_hash, two_hash],
                [five_hash, six_hash],
                4,
            ),
            # Same as above, one had a block created after five so it comes second.
            BlockType.SOFT_BLOCKED: (
                [five_hash, one_hash],
                [three_hash, four_hash],
                4,
            ),
        }

        assert second_mlbf.generate_and_write_stash(previous_mlbf=first_mlbf) == {
            'blocked': [three_hash, two_hash],
            'softblocked': [five_hash, one_hash],
            # 3 and 5 are omitted because they transitioned
            # from one block type to another
            'unblocked': [six_hash, four_hash],
        }

    def test_generate_stash_returns_expected_stash(self):
        addon, block = self._blocked_addon()
        block_versions = [
            self._block_version(block, self._version(addon)) for _ in range(10)
        ]
        mlbf = MLBF.generate_from_db('test')
        mlbf.generate_and_write_stash()

        expected_blocked = [
            (block_version.block.guid, block_version.version.version)
            for block_version in block_versions
        ]

        with mlbf.storage.open(mlbf.stash_path, 'r') as f:
            assert json.load(f) == {
                'blocked': MLBF.hash_filter_inputs(expected_blocked),
                # Soft blocked is empty because the waffle switch is off
                'softblocked': [],
                'unblocked': [],
            }

        assert mlbf.generate_and_write_stash() == {
            'blocked': MLBF.hash_filter_inputs(expected_blocked),
            'softblocked': [],
            'unblocked': [],
        }

        # Remove the last block version
        block_versions[-1].delete()
        expected_unblocked = expected_blocked[-1:]

        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_and_write_stash(previous_mlbf=mlbf) == {
            'blocked': [],
            'softblocked': [],
            'unblocked': MLBF.hash_filter_inputs(expected_unblocked),
        }

    @mock.patch('olympia.blocklist.mlbf.get_base_replace_threshold')
    def test_generate_empty_stash_when_all_items_in_filter(
        self, mock_get_base_replace_threshold
    ):
        mock_get_base_replace_threshold.return_value = 2
        # Add a hard blocked version and 2 soft blocked versions
        addon, block = self._blocked_addon(
            file_kw={'is_signed': True}, block_type=BlockType.BLOCKED
        )
        hard_block = block.blockversion_set.first()
        (hard_block_hash,) = MLBF.hash_filter_inputs(
            [(block.guid, hard_block.version.version)]
        )
        soft_blocks = [
            self._block_version(
                block, self._version(addon), block_type=BlockType.SOFT_BLOCKED
            )
            for _ in range(2)
        ]

        base_mlbf = MLBF.generate_from_db('base')

        # Transition the hard block to soft blocked
        # and delete the other soft blocks
        hard_block.update(block_type=BlockType.SOFT_BLOCKED)
        for soft_block in soft_blocks:
            soft_block.delete()

        mlbf = MLBF.generate_from_db('test')

        assert mlbf.should_upload_filter(BlockType.SOFT_BLOCKED, base_mlbf)
        # We have a softened block so we should upload stash, even though
        # it will be empty since the block will be handled by the filter
        assert mlbf.should_upload_stash(BlockType.BLOCKED, base_mlbf)

        # If soft blocking is enabled, then we will expect a new soft block filter
        # and no softblock stash since the blocks will be handled by the filter
        # similarly we do not include the blocked version in the unblocked stash
        # because it is now soft blocked.
        # We actually would like this to result in no stash being created
        # Bug: https://github.com/mozilla/addons/issues/15202
        assert mlbf.generate_and_write_stash(
            previous_mlbf=base_mlbf,
            blocked_base_filter=base_mlbf,
            soft_blocked_base_filter=base_mlbf,
        ) == {
            'blocked': [],
            'softblocked': [],
            'unblocked': [],
        }

    def test_generate_filter_returns_expected_data(self):
        addon, block = self._blocked_addon()
        not_blocked = self._version(addon)
        not_blocked_version = not_blocked.version
        hard_blocked = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        hard_blocked_version = hard_blocked.version.version
        soft_blocked = self._block_version(
            block, self._version(addon), block_type=BlockType.SOFT_BLOCKED
        )
        soft_blocked_version = soft_blocked.version.version
        mlbf = MLBF.generate_from_db('test')

        mlbf.generate_and_write_filter(BlockType.BLOCKED).verify(
            include=MLBF.hash_filter_inputs([(addon.guid, hard_blocked_version)]),
            exclude=MLBF.hash_filter_inputs(
                [(addon.guid, soft_blocked_version), (addon.guid, not_blocked_version)]
            ),
        )

        mlbf.generate_and_write_filter(BlockType.SOFT_BLOCKED).verify(
            include=MLBF.hash_filter_inputs([(addon.guid, soft_blocked_version)]),
            exclude=MLBF.hash_filter_inputs(
                [(addon.guid, hard_blocked_version), (addon.guid, not_blocked_version)]
            ),
        )

    @mock.patch('olympia.blocklist.mlbf.generate_mlbf')
    def test_generate_filter_does_not_pass_duplicate_guids(self, mock_generate_mlbf):
        """
        Ensure that the filter we create does not include duplicate guids
        that would needlessly increase the size of the filter
        without improving accuracy.

        NOTE: It is now impossible to reuse a guid but there are legacy addons
        that do this. This test verifies against this scenario using
        the addon.addonguid obfuscation.
        """
        version = '2.1'
        addon_one = addon_factory(
            status=amo.STATUS_DELETED,
            guid='one',
            version_kw={'version': version},
            file_kw={'is_signed': True},
        )
        addon_two = addon_factory(
            guid='two',
            version_kw={'version': version},
            file_kw={'is_signed': True},
        )

        addon_two.update(guid=GUID_REUSE_FORMAT.format(addon_one.id))
        addon_two.addonguid.update(guid=addon_one.guid)

        mlbf = MLBF.generate_from_db('test')

        mlbf.generate_and_write_filter(BlockType.BLOCKED)

        # The guid of the reused addon should be the same as the original addon
        assert addon_two.addonguid_guid == addon_one.addonguid_guid

        assert mock_generate_mlbf.call_args_list == [
            mock.call(
                stats=mock.ANY,
                include=[],
                exclude=MLBF.hash_filter_inputs([(addon_one.guid, version)]),
            )
        ]

    def test_changed_count_returns_expected_count(self):
        addon, block = self._blocked_addon()
        self._block_version(block, self._version(addon), block_type=BlockType.BLOCKED)
        first_mlbf = MLBF.generate_from_db('first')
        # Include the new blocked version
        assert first_mlbf.blocks_changed_since_previous(BlockType.BLOCKED) == 1
        assert first_mlbf.blocks_changed_since_previous(BlockType.SOFT_BLOCKED) == 0
        self._block_version(block, self._version(addon), block_type=BlockType.BLOCKED)
        # The count should not change because the data is already calculated
        assert first_mlbf.blocks_changed_since_previous(BlockType.BLOCKED) == 1
        assert first_mlbf.blocks_changed_since_previous(BlockType.SOFT_BLOCKED) == 0
        self._block_version(
            block, self._version(addon), block_type=BlockType.SOFT_BLOCKED
        )
        next_mlbf = MLBF.generate_from_db('next')
        # The count should include both blocked versions and the soft blocked version
        # since we are not comparing to a previous mlbf
        assert next_mlbf.blocks_changed_since_previous(BlockType.BLOCKED) == 2
        assert next_mlbf.blocks_changed_since_previous(BlockType.SOFT_BLOCKED) == 1
        # When comparing to the first mlbf,
        # the count should only include the second block
        assert (
            next_mlbf.blocks_changed_since_previous(
                previous_mlbf=first_mlbf, block_type=BlockType.BLOCKED
            )
            == 1
        )
        # The count should still include the soft blocked version since it was
        # created after the first_mlbf
        assert (
            next_mlbf.blocks_changed_since_previous(
                previous_mlbf=first_mlbf, block_type=BlockType.SOFT_BLOCKED
            )
            == 1
        )
        final_mlbf = MLBF.generate_from_db('final')
        # The soft blocked version is no longer a change comparing to the previous mlbf
        # but is still a change to the original mlbf from before it was created
        assert (
            final_mlbf.blocks_changed_since_previous(
                previous_mlbf=next_mlbf,
                block_type=BlockType.SOFT_BLOCKED,
            )
            == 0
        )
        assert (
            final_mlbf.blocks_changed_since_previous(
                previous_mlbf=first_mlbf,
                block_type=BlockType.BLOCKED,
            )
            == 1
        )

    def _test_not_raises_if_versions_blocked(self, block_type: BlockType):
        mlbf = MLBF.generate_from_db('test')
        self._blocked_addon(file_kw={'is_signed': True}, block_type=block_type)
        assert mlbf.data[block_type] == []
        mlbf.generate_and_write_filter(block_type)

    def test_generate_filter_not_raises_if_all_versions_unblocked(self):
        """
        When we create a bloom filter where all versions fall into
        the "not filtered" category This can create invalid error rates
        because the error rate depends on these numbers being non-zero.
        """
        self._test_not_raises_if_versions_blocked(BlockType.BLOCKED)

    def test_generate_filter_not_raises_if_all_versions_blocked(self):
        """
        When we create a bloom filter where all versions fall into
        the "not filtered" category This can create invalid error rates
        because the error rate depends on these numbers being non-zero.
        """
        self._test_not_raises_if_versions_blocked(BlockType.SOFT_BLOCKED)

    def test_duplicate_guid_is_blocked(self):
        """
        Test that if there are addons with duplicated guids, and one is blocked,
        the addon should be blocked and the other should not be included in not_blocked
        """
        version = '2.1'
        reused_addon = addon_factory(
            status=amo.STATUS_DELETED,
            version_kw={'version': version},
            file_kw={'is_signed': True},
        )
        addon, block = self._blocked_addon(
            version_kw={'version': version},
            file_kw={'is_signed': True},
        )

        reused_addon.update(guid=GUID_REUSE_FORMAT.format(addon.id))
        reused_addon.addonguid.update(guid=addon.guid)

        (reused_addon_hash,) = MLBF.hash_filter_inputs(
            [(reused_addon.addonguid.guid, version)]
        )

        soft_blocked_version = self._block_version(
            block, self._version(addon), block_type=BlockType.SOFT_BLOCKED
        )

        mlbf = MLBF.generate_from_db('test')

        (block_version_hash,) = MLBF.hash_filter_inputs([(addon.guid, version)])
        (soft_blocked_version_hash,) = MLBF.hash_filter_inputs(
            [(soft_blocked_version.block.guid, soft_blocked_version.version.version)]
        )

        # There is a duplicate hash but we will exclude it from the not_blocked versions
        assert block_version_hash == reused_addon_hash

        assert mlbf.data.blocked_items == [block_version_hash]
        assert mlbf.data.soft_blocked_items == [soft_blocked_version_hash]
        assert mlbf.data.not_blocked_items == []

    def test_no_soft_blocked_versions_empty_array(self):
        addon, block = self._blocked_addon()
        self._block_version(block, self._version(addon), block_type=BlockType.BLOCKED)
        mlbf = MLBF.generate_from_db('test')
        assert (
            BlockVersion.objects.filter(
                block_type=BlockType.SOFT_BLOCKED,
                version__file__is_signed=True,
            ).count()
            == 0
        )
        assert mlbf.data.soft_blocked_items == []

    def test_no_hard_blocked_versions_empty_array(self):
        addon, block = self._blocked_addon()
        self._block_version(
            block, self._version(addon), block_type=BlockType.SOFT_BLOCKED
        )
        mlbf = MLBF.generate_from_db('test')
        assert (
            BlockVersion.objects.filter(
                block_type=BlockType.BLOCKED,
                version__file__is_signed=True,
            ).count()
            == 0
        )
        assert mlbf.data.blocked_items == []

    def test_validate_duplicate_item_in_single_data_type(self):
        """
        Test that if an item is found more than once in a single data type
        then the cache.json fails validation.
        """
        mlbf = MLBF.generate_from_db('test')
        with open(mlbf.data._cache_path, 'w') as f:
            json.dump(
                {
                    'blocked': ['guid:version', 'guid:version'],
                    'soft_blocked': [],
                    'not_blocked': [],
                },
                f,
            )
        mlbf = MLBF.load_from_storage(mlbf.created_at)

        with self.assertRaises(ValueError) as e:
            mlbf.validate()

        assert (
            'Item guid:version found 2 times in data type '
            f'{MLBFDataType.BLOCKED.name}'
        ) in str(e.exception)

    def test_validate_duplicate_item_in_multiple_data_types(self):
        """
        Test that if an item is found in multiple data types, it is not valid
        """
        mlbf = MLBF.generate_from_db('test')
        with open(mlbf.data._cache_path, 'w') as f:
            json.dump(
                {
                    'blocked': ['guid:version'],
                    'soft_blocked': ['guid:version'],
                    'not_blocked': [],
                },
                f,
            )
        mlbf = MLBF.load_from_storage(mlbf.created_at)

        with self.assertRaises(ValueError) as e:
            mlbf.validate()

        assert (
            'Item guid:version found in multiple data types: '
            f'{MLBFDataType.BLOCKED.name}, {MLBFDataType.SOFT_BLOCKED.name}'
        ) in str(e.exception)
