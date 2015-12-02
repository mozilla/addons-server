import collections


def attach_share_counts(StatsModel, key, objects):
    """
    Populate obj.share_counts for each obj in the dict objects.

    * StatsModel is used to run the query.
    * key is the name of the foreign key.
    * objects is a dict of {obj.id: obj}.
    """
    for obj in objects.values():
        obj.share_counts = collections.defaultdict(int)
    qs = (StatsModel.objects.filter(**{'%s__in' % key: objects})
          .values_list(key, 'service', 'count'))
    for pk, service, count in qs:
        objects[pk].share_counts[service] = count
