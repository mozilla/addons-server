import os

import amo.search
from .models import Reindexing
from django.core.management.base import CommandError


# shortcut functions
is_reindexing_amo = Reindexing.objects.is_reindexing_amo
flag_reindexing_amo = Reindexing.objects.flag_reindexing_amo
unflag_reindexing_amo = Reindexing.objects.unflag_reindexing_amo
get_indices = Reindexing.objects.get_indices


def index_objects(ids, model, search, index=None, transforms=None):
    if index is None:
        index = model._get_index()

    indices = Reindexing.objects.get_indices(index)

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


def raise_if_reindex_in_progress(site):
    """Checks if the database indexation flag is on for the given site.

    If it's on, and if no "FORCE_INDEXING" variable is present in the env,
    raises a CommandError.
    """
    already_reindexing = Reindexing.objects._is_reindexing(site)
    if already_reindexing and 'FORCE_INDEXING' not in os.environ:
        raise CommandError("Indexation already occuring. Add a FORCE_INDEXING "
                           "variable in the environ to force it")
