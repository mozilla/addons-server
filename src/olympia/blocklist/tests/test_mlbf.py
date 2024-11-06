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

    def _blocked_addon(self, **kwargs):
        addon = addon_factory(**kwargs)
        block = block_factory(guid=addon.guid, updated_by=self.user)
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


class TestMLBFDataBaseLoader(_MLBFBase):
    def test_load_returns_expected_data(self):
        """
        Test that the class returns a dictionary mapping the
        expected TestMLBFDataBaseLoader keys to the blocked and notblocked item lists.
        """
        addon, block = self._blocked_addon()

        notblocked_version = addon.current_version
        block_version = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )

        mlbf_data = MLBFDataBaseLoader(self.storage)
        assert mlbf_data[MLBFDataType.BLOCKED] == MLBF.hash_filter_inputs(
            [(block_version.block.guid, block_version.version.version)]
        )
        assert mlbf_data[MLBFDataType.NOT_BLOCKED] == MLBF.hash_filter_inputs(
            [(notblocked_version.addon.guid, notblocked_version.version)]
        )

    def test_blocked_items_caches_excluded_version_ids(self):
        """
        Test that accessing the blocked_items property caches the version IDs
        to exclude in the notblocked_items property.
        """
        addon, block = self._blocked_addon()
        block_version = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        with self.assertNumQueries(2):
            mlbf_data = MLBFDataBaseLoader(self.storage)
        assert (
            MLBF.hash_filter_inputs(
                [(block_version.block.guid, block_version.version.version)]
            )
            not in mlbf_data.blocked_items
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

        assert base_mlbf.generate_diffs() == (
            set(
                MLBF.hash_filter_inputs(
                    [(addon.block.guid, addon.current_version.version)]
                )
            ),
            set(),
            1,
        )

        next_mlbf = MLBF.generate_from_db('next')
        # If we don't include the base_mlbf, unblocked version will still be in the diff
        assert next_mlbf.generate_diffs() == (
            set(
                MLBF.hash_filter_inputs(
                    [(addon.block.guid, addon.current_version.version)]
                )
            ),
            set(),
            1,
        )
        # Providing a previous mlbf with the unblocked version already included
        # removes it from the diff
        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == (set(), set(), 0)

    def test_diff_no_changes(self):
        addon, block = self._blocked_addon()
        self._block_version(block, self._version(addon), block_type=BlockType.BLOCKED)
        base_mlbf = MLBF.generate_from_db('test')
        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == (set(), set(), 0)

    def test_diff_block_added(self):
        addon, block = self._blocked_addon()
        base_mlbf = MLBF.generate_from_db('test')

        new_block = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )

        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == (
            set(
                MLBF.hash_filter_inputs(
                    [(new_block.block.guid, new_block.version.version)]
                )
            ),
            set(),
            1,
        )

    def test_diff_block_removed(self):
        addon, block = self._blocked_addon()
        block_version = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        base_mlbf = MLBF.generate_from_db('test')
        block_version.delete()
        next_mlbf = MLBF.generate_from_db('test_two')

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == (
            set(),
            set(
                MLBF.hash_filter_inputs(
                    [(block_version.block.guid, block_version.version.version)]
                )
            ),
            1,
        )

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

        assert next_mlbf.generate_diffs(previous_mlbf=base_mlbf) == (
            set(
                MLBF.hash_filter_inputs(
                    [(new_block.block.guid, new_block.version.version)]
                )
            ),
            set(
                MLBF.hash_filter_inputs(
                    [(block_version.block.guid, block_version.version.version)]
                )
            ),
            2,
        )

    def test_generate_stash_returns_expected_stash(self):
        addon, block = self._blocked_addon()
        block_version = self._block_version(
            block, self._version(addon), block_type=BlockType.BLOCKED
        )
        mlbf = MLBF.generate_from_db('test')
        mlbf.generate_and_write_stash()

        with mlbf.storage.open(mlbf.stash_path, 'r') as f:
            assert json.load(f) == {
                'blocked': MLBF.hash_filter_inputs(
                    [(block_version.block.guid, block_version.version.version)]
                ),
                'unblocked': [],
            }
        block_version.delete()

        next_mlbf = MLBF.generate_from_db('test_two')
        next_mlbf.generate_and_write_stash(previous_mlbf=mlbf)
        with next_mlbf.storage.open(next_mlbf.stash_path, 'r') as f:
            assert json.load(f) == {
                'blocked': [],
                'unblocked': MLBF.hash_filter_inputs(
                    [(block_version.block.guid, block_version.version.version)]
                ),
            }

    def test_changed_count_returns_expected_count(self):
        addon, block = self._blocked_addon()
        self._block_version(block, self._version(addon), block_type=BlockType.BLOCKED)
        first_mlbf = MLBF.generate_from_db('first')
        # Include the new blocked version
        assert first_mlbf.blocks_changed_since_previous() == 1
        self._block_version(block, self._version(addon), block_type=BlockType.BLOCKED)
        # The count should not change because the data is already calculated
        assert first_mlbf.blocks_changed_since_previous() == 1
        next_mlbf = MLBF.generate_from_db('next')
        # The count should include both blocked versions since we are not comparing
        assert next_mlbf.blocks_changed_since_previous() == 2
        # When comparing to the first mlbf,
        # the count should only include the second block
        assert next_mlbf.blocks_changed_since_previous(previous_mlbf=first_mlbf) == 1

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

        self._block_version(
            block, self._version(addon), block_type=BlockType.SOFT_BLOCKED
        )

        mlbf = MLBF.generate_from_db('test')

        (block_version,) = MLBF.hash_filter_inputs([(addon.guid, version)])
        assert block_version in mlbf.data.blocked_items
        assert block_version not in mlbf.data.not_blocked_items

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
