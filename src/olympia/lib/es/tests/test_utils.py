from unittest import mock

from olympia.addons.indexers import AddonIndexer
from olympia.amo.tests import addon_factory, TestCase
from olympia.lib.es.models import Reindexing
from olympia.lib.es.utils import index_objects, get_major_version


@mock.patch('olympia.lib.es.utils.get_major_version')
@mock.patch('olympia.lib.es.utils.helpers')
class TestIndexObjects(TestCase):
    def test_index_objects(self, helpers_mock, get_major_version_mock):
        get_major_version_mock.return_value = 6
        addon1 = addon_factory()
        addon2 = addon_factory()
        fake_extract = {
            addon1.pk: mock.Mock(),
            addon2.pk: mock.Mock(),
        }
        with mock.patch.object(
            AddonIndexer, 'extract_document', lambda a: fake_extract[a.pk]
        ):
            index_objects(ids=[addon1.pk, addon2.pk], indexer_class=AddonIndexer)
        bulk_mock = helpers_mock.bulk
        assert bulk_mock.call_count == 1
        assert bulk_mock.call_args[0][1] == [
            {
                '_source': fake_extract[addon1.pk],
                '_id': addon1.pk,
                '_index': 'test_amo_addons',
                '_type': 'addons',
            },
            {
                '_source': fake_extract[addon2.pk],
                '_id': addon2.pk,
                '_index': 'test_amo_addons',
                '_type': 'addons',
            },
        ]

    def test_index_objects_elasticsearch_7(self, helpers_mock, get_major_version_mock):
        get_major_version_mock.return_value = 7
        addon1 = addon_factory()
        addon2 = addon_factory()
        fake_extract = {
            addon1.pk: mock.Mock(),
            addon2.pk: mock.Mock(),
        }
        with mock.patch.object(
            AddonIndexer, 'extract_document', lambda a: fake_extract[a.pk]
        ):
            index_objects(ids=[addon1.pk, addon2.pk], indexer_class=AddonIndexer)
        bulk_mock = helpers_mock.bulk
        assert bulk_mock.call_count == 1
        assert bulk_mock.call_args[0][1] == [
            {
                '_source': fake_extract[addon1.pk],
                '_id': addon1.pk,
                '_index': 'test_amo_addons',
            },
            {
                '_source': fake_extract[addon2.pk],
                '_id': addon2.pk,
                '_index': 'test_amo_addons',
            },
        ]

    def test_index_objects_with_index(self, helpers_mock, get_major_version_mock):
        target_index = 'amazing_index'
        get_major_version_mock.return_value = 6
        addon1 = addon_factory()
        addon2 = addon_factory()
        fake_extract = {
            addon1.pk: mock.Mock(),
            addon2.pk: mock.Mock(),
        }
        with mock.patch.object(
            AddonIndexer, 'extract_document', lambda a: fake_extract[a.pk]
        ):
            index_objects(
                ids=[addon1.pk, addon2.pk],
                indexer_class=AddonIndexer,
                index=target_index,
            )
        bulk_mock = helpers_mock.bulk
        assert bulk_mock.call_count == 1
        assert bulk_mock.call_args[0][1] == [
            {
                '_source': fake_extract[addon1.pk],
                '_id': addon1.pk,
                '_index': target_index,
                '_type': 'addons',
            },
            {
                '_source': fake_extract[addon2.pk],
                '_id': addon2.pk,
                '_index': target_index,
                '_type': 'addons',
            },
        ]

    def test_index_objects_while_reindexing(self, helpers_mock, get_major_version_mock):
        target_index = AddonIndexer.get_index_alias()  # the default index
        Reindexing.objects.create(
            alias=target_index, old_index='old_index', new_index='new_index'
        )
        get_major_version_mock.return_value = 6
        addon1 = addon_factory()
        addon2 = addon_factory()
        fake_extract = {
            addon1.pk: mock.Mock(),
            addon2.pk: mock.Mock(),
        }
        with mock.patch.object(
            AddonIndexer, 'extract_document', lambda a: fake_extract[a.pk]
        ):
            index_objects(
                ids=[addon1.pk, addon2.pk],
                indexer_class=AddonIndexer,
            )
        bulk_mock = helpers_mock.bulk
        assert bulk_mock.call_count == 1
        # We're reindexing and didn't specify an index: index_object() is going
        # to index our objects on both the old and the new indices instead of
        # the alias.
        assert bulk_mock.call_args[0][1] == [
            {
                '_source': fake_extract[addon1.pk],
                '_id': addon1.pk,
                '_index': 'new_index',
                '_type': 'addons',
            },
            {
                '_source': fake_extract[addon1.pk],
                '_id': addon1.pk,
                '_index': 'old_index',
                '_type': 'addons',
            },
            {
                '_source': fake_extract[addon2.pk],
                '_id': addon2.pk,
                '_index': 'new_index',
                '_type': 'addons',
            },
            {
                '_source': fake_extract[addon2.pk],
                '_id': addon2.pk,
                '_index': 'old_index',
                '_type': 'addons',
            },
        ]

    def test_index_objects_with_index_while_reindexing(
        self, helpers_mock, get_major_version_mock
    ):
        target_index = 'amazing_index'
        Reindexing.objects.create(
            alias=target_index, old_index='old_index', new_index='new_index'
        )
        get_major_version_mock.return_value = 6
        addon1 = addon_factory()
        addon2 = addon_factory()
        fake_extract = {
            addon1.pk: mock.Mock(),
            addon2.pk: mock.Mock(),
        }
        with mock.patch.object(
            AddonIndexer, 'extract_document', lambda a: fake_extract[a.pk]
        ):
            index_objects(
                ids=[addon1.pk, addon2.pk],
                indexer_class=AddonIndexer,
                index=target_index,
            )
        bulk_mock = helpers_mock.bulk
        assert bulk_mock.call_count == 1
        # We're reindexing but we specified which index to use so it doesn't
        # matter.
        assert bulk_mock.call_args[0][1] == [
            {
                '_source': fake_extract[addon1.pk],
                '_id': addon1.pk,
                '_index': 'amazing_index',
                '_type': 'addons',
            },
            {
                '_source': fake_extract[addon2.pk],
                '_id': addon2.pk,
                '_index': 'amazing_index',
                '_type': 'addons',
            },
        ]


def test_get_major_version():
    info = {
        'name': '_w5frMV',
        'cluster_name': 'docker-cluster',
        'cluster_uuid': 'SGCal9MVRN6JKOQptxOQJA',
        'version': {
            'number': '6.8.23',
            'build_flavor': 'default',
            'build_type': 'docker',
            'build_hash': '4f67856',
            'build_date': '2022-01-06T21:30:50.087716Z',
            'build_snapshot': False,
            'lucene_version': '7.7.3',
            'minimum_wire_compatibility_version': '5.6.0',
            'minimum_index_compatibility_version': '5.0.0',
        },
        'tagline': 'You Know, for Search',
    }
    get_major_version(mock.Mock(info=lambda: info)) == 6

    info['version']['number'] = '7.17.2'
    get_major_version(mock.Mock(info=lambda: info)) == 7
