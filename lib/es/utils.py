import os

import amo.search
from .models import Reindexing
from django.core.management.base import CommandError


def get_indices(index):
    # Do we have a reindexing going on ?
    try:
        reindex = Reindexing.objects.get(alias=index)
        # Yes. Let's reindex on both indexes
        return [idx for idx in reindex.new_index, reindex.old_index
                if idx is not None]
    except Reindexing.DoesNotExist:
        return [index]


def index_objects(ids, model, search, index=None, transforms=None):
    if index is None:
        index = model._get_index()

    indices = get_indices(index)

    if transforms is None:
        transforms = []

    qs = model.objects.no_cache().filter(id__in=ids)
    for t in transforms:
        qs = qs.transform(t)

    for ob in qs:
        data = search.extract(ob)

        for index in indices:
            model.index(data, bulk=True, id=ob.id, index=index)

    amo.search.get_es().flush_bulk(forced=True)


def database_flagged():
    """Returns True if the Database is being indexed"""
    return Reindexing.objects.exists()


def raise_if_reindex_in_progress():
    """Checks if the database indexation flag is on.

    If it's one, and if no "FORCE_INDEXING" variable is present in the env,
    raises a CommandError.
    """
    if database_flagged() and 'FORCE_INDEXING' not in os.environ:
        raise CommandError("Indexation already occuring. Add a FORCE_INDEXING "
                           "variable in the environ to force it")
