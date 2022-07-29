from unittest import mock

from olympia.addons.indexers import AddonIndexer
from olympia.addons.models import Addon
from olympia.amo.tests import addon_factory, ESTestCase, TestCase
from olympia.search.models import Reindexing
from olympia.search.utils import get_es, index_objects, unindex_objects


class TestGetES(ESTestCase):
    def test_get_es(self):
        es = get_es()
        assert es.transport._verified_elasticsearch


@mock.patch('olympia.search.utils.helpers')
class TestIndexObjects(TestCase):
    def test_index_objects(self, helpers_mock):
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
                queryset=Addon.objects.filter(id__in=(addon1.pk, addon2.pk)),
                indexer_class=AddonIndexer,
            )
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

    def test_index_objects_with_index(self, helpers_mock):
        target_index = 'amazing_index'
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
                queryset=Addon.objects.filter(id__in=(addon1.pk, addon2.pk)),
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
            },
            {
                '_source': fake_extract[addon2.pk],
                '_id': addon2.pk,
                '_index': target_index,
            },
        ]

    def test_index_objects_while_reindexing(self, helpers_mock):
        target_index = AddonIndexer.get_index_alias()  # the default index
        Reindexing.objects.create(
            alias=target_index, old_index='old_index', new_index='new_index'
        )
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
                queryset=Addon.objects.filter(id__in=(addon1.pk, addon2.pk)),
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
            },
            {
                '_source': fake_extract[addon1.pk],
                '_id': addon1.pk,
                '_index': 'old_index',
            },
            {
                '_source': fake_extract[addon2.pk],
                '_id': addon2.pk,
                '_index': 'new_index',
            },
            {
                '_source': fake_extract[addon2.pk],
                '_id': addon2.pk,
                '_index': 'old_index',
            },
        ]

    def test_index_objects_with_index_while_reindexing(self, helpers_mock):
        target_index = 'amazing_index'
        Reindexing.objects.create(
            alias=target_index, old_index='old_index', new_index='new_index'
        )
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
                queryset=Addon.objects.filter(id__in=(addon1.pk, addon2.pk)),
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
            },
            {
                '_source': fake_extract[addon2.pk],
                '_id': addon2.pk,
                '_index': 'amazing_index',
            },
        ]


class TestUnindexObjects(ESTestCase):
    def test_unindex_objects(self):
        def _es_search_ids():
            return [
                o['_id'] for o in es.search(query={'match_all': {}})['hits']['hits']
            ]

        es = get_es()
        addon1 = addon_factory()
        addon2 = addon_factory()
        addon3 = addon_factory()
        assert list(Addon.objects.all().values_list('id', flat=True)) == [
            addon1.pk,
            addon2.pk,
            addon3.pk,
        ]
        self.reindex(Addon)
        assert es.count()['count'] == 3, _es_search_ids()

        unindex_objects((addon1.id,), indexer_class=AddonIndexer)
        self.refresh()
        assert es.count()['count'] == 2, _es_search_ids()

        unindex_objects((addon1.id, addon2.id), indexer_class=AddonIndexer)
        self.refresh()
        assert es.count()['count'] == 1, _es_search_ids()
