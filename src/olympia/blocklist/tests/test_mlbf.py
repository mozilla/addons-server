import json
from functools import cached_property

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


class TestMLBF(_MLBFBase):
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

    def test_diff_block_added(self):
        addon, block = self._blocked_addon()
        base_mlbf = MLBF.generate_from_db('test')

        new_block = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )

        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == {
            BlockType.BLOCKED: (
                MLBF.hash_filter_inputs(
                    [(new_block.block.guid, new_block.version.version)]
                ),
                [],
                1,
            ),
            BlockType.SOFT_BLOCKED: ([], [], 0),
        }

    def test_diff_block_removed(self):
        addon, block = self._blocked_addon()
        block_version = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        base_mlbf = MLBF.generate_from_db('test')
        block_version.delete()
        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == {
            BlockType.BLOCKED: (
                [],
                MLBF.hash_filter_inputs(
                    [(block_version.block.guid, block_version.version.version)]
                ),
                1,
            ),
            BlockType.SOFT_BLOCKED: ([], [], 0),
        }

    def test_diff_block_added_and_removed(self):
        addon, block = self._blocked_addon()
        block_version = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        base_mlbf = MLBF.generate_from_db('test')

        new_block = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        block_version.delete()

        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == {
            BlockType.BLOCKED: (
                MLBF.hash_filter_inputs(
                    [(new_block.block.guid, new_block.version.version)]
                ),
                MLBF.hash_filter_inputs(
                    [(block_version.block.guid, block_version.version.version)]
                ),
                2,
            ),
            BlockType.SOFT_BLOCKED: ([], [], 0),
        }

    def test_diff_block_hard_to_soft(self):
        addon, block = self._blocked_addon()
        block_version = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        base_mlbf = MLBF.generate_from_db('test')
        block_version.update(block_type=BlockType.SOFT_BLOCKED)
        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == {
            BlockType.BLOCKED: (
                [],
                MLBF.hash_filter_inputs(
                    [(block_version.block.guid, block_version.version.version)]
                ),
                1,
            ),
            BlockType.SOFT_BLOCKED: (
                MLBF.hash_filter_inputs(
                    [(block_version.block.guid, block_version.version.version)]
                ),
                [],
                1,
            ),
        }

    def test_diff_block_soft_to_hard(self):
        addon, block = self._blocked_addon()
        block_version = self._block_version(
            block, self._version(addon), block_type=BlockType.SOFT_BLOCKED
        )
        base_mlbf = MLBF.generate_from_db('test')
        block_version.update(block_type=BlockType.BLOCKED)
        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == {
            BlockType.BLOCKED: (
                MLBF.hash_filter_inputs(
                    [(block_version.block.guid, block_version.version.version)]
                ),
                [],
                1,
            ),
            BlockType.SOFT_BLOCKED: (
                [],
                MLBF.hash_filter_inputs(
                    [(block_version.block.guid, block_version.version.version)]
                ),
                1,
            ),
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
                'unblocked': [],
            }

        # Remove the last block version
        block_versions[-1].delete()
        expected_unblocked = expected_blocked[-1:]

        next_mlbf = MLBF.generate_from_db('test_two')
        next_mlbf.generate_and_write_stash(previous_mlbf=mlbf)

        with next_mlbf.storage.open(next_mlbf.stash_path, 'r') as f:
            assert json.load(f) == {
                'blocked': [],
                'unblocked': MLBF.hash_filter_inputs(expected_unblocked),
            }

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

    def test_generate_filter_not_raises_if_all_versions_unblocked(self):
        """
        When we create a bloom filter where all versions fall into
        the "not filtered" category This can create invalid error rates
        because the error rate depends on these numbers being non-zero.
        """
        mlbf = MLBF.generate_from_db('test')
        self._blocked_addon(file_kw={'is_signed': True})
        assert mlbf.data.blocked_items == []
        mlbf.generate_and_write_filter()

    def test_generate_filter_not_raises_if_all_versions_blocked(self):
        """
        When we create a bloom filter where all versions fall into
        the "not filtered" category This can create invalid error rates
        because the error rate depends on these numbers being non-zero.
        """
        mlbf = MLBF.generate_from_db('test')
        self._blocked_addon(file_kw={'is_signed': False})
        assert mlbf.data.not_blocked_items == []
        mlbf.generate_and_write_filter()

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
