from .models import Reindexing
import elasticutils.contrib.django as elasticutils


def get_indices(index):
    # Do we have a reindexing going on ?
    try:
        reindex = Reindexing.objects.get(alias=index)
        # Yes. Let's reindex on both indexes
        return [index for index in
                reindex.new_index, reindex.old_index
                if index is not None]
    except Reindexing.DoesNotExist:
        return [index]


def index_objects(ids, model, search, index=None, transforms=None):
    if index is None:
        index = model._get_index()

    indices = get_indices(index)

    if transforms is None:
        transforms = []

    qs = model.uncached.filter(id__in=ids)
    for t in transforms:
        qs = qs.transform(t)

    for ob in qs:
        data = search.extract(ob)

        for index in indices:
            model.index(data, bulk=True, id=ob.id, index=index)

    elasticutils.get_es().flush_bulk(forced=True)
