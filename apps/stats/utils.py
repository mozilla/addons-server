from decimal import Decimal

from .db import StatsDict


class DictKey(object):
    """A simple wrapper used to prevent collisions with string dictionary keys.

    Used by ``unknown_gen``.
    """

    def __init__(self, name):
        self.name = name

    def __str__(self):
        return str(self.name)


def csv_prep(stats, field_list, precision='1'):
    """Prepare simple stats for CSV output.

    This is suitable for simple stats without any breakdowns.
    All Decimal values will be quantized to the given ``precision``.

    Returns a tuple containing a row generator and a list of field
    names suitable for the CSV header.
    """
    fields = [k for k, v in field_list]
    stats = quantize_gen(stats, None, precision)
    stats = values_gen(stats, fields, zero_val=0)
    return (stats, fields)


def csv_dynamic_prep(stats, queryset, field_list, total_key, dynamic_key):
    """Prepare dynamic stats for CSV output.

    This is suitable for stats containing breakdown values.
    All Decimal values will be rounded and converted to integers.

    Returns a tuple containing a row generator and a list of field
    names suitable for the CSV header.
    """
    if not queryset:
        return ([], [])

    # Summarize entire queryset to get all dynamic field names and
    # determine if we need to calculate 'unknown' values.
    totals = queryset.summary(**dict(field_list))

    # Since there may be averages in play, round all decimals to integers
    totals = list(decimal_to_int_gen([totals]))[0]
    stats = decimal_to_int_gen(stats)

    # Perform 'unknown' calculations if there is a difference between
    # dynamic field total and grand total.
    dyn_sum = totals[dynamic_key].sum_reduce()
    if dyn_sum < totals[total_key]:
        totals[dynamic_key]['unknown'] = totals[total_key] - dyn_sum
        stats = unknown_gen(stats, total_key, dynamic_key)

    # Flatten the nested dynamic dictionary, grab all keys and sort them
    # by their values.
    d = flatten_dict({dynamic_key: totals[dynamic_key]})
    dyn_keys = sorted(d, key=d.__getitem__, reverse=True)

    # Build the final list of field keys, replacing dynamic_key with all its
    # breakdown fields in dyn_keys.
    dyn_index = zip(*field_list)[0].index(dynamic_key)
    fields = [k for k, v in field_list[:dyn_index]]
    fields.extend(k for k in dyn_keys)
    fields.extend(k for k, v in field_list[dyn_index + 1:])

    # For CSV headers, we trim the "dynamic_key/" portion from the start of all
    # the dyn_keys.
    headings = [k for k, v in field_list[:dyn_index]]
    headings.extend(k[len(dynamic_key) + 1:] for k in dyn_keys)
    headings.extend(k for k, v in field_list[dyn_index + 1:])

    # Almost done...
    # For each row: flatten the dynamic field dictionary, and turn the row
    # into a list of values.
    stats = flatten_gen(stats, flatten_key=dynamic_key)
    stats = values_gen(stats, fields, zero_val=0)

    return (stats, headings)


def flatten_dict(d, key=None):
    """Flatten a nested dictionary.

    If `key` is specified, only flatten its corresponding value.
    Otherwise flatten all values in the dictionary. Example:

    >>> flatten({'a': 1, 'b': {'c': 2, 'd': 3}})
    {'a': 1, 'b/c': 2, 'b/d': 3}
    """

    def inner(d, key=None):
        for k, v in d.items():
            if (key is None or key == k) and isinstance(v, dict):
                for k2, v2 in inner(v):
                    yield (u'%s/%s' % (k, k2), v2)
            else:
                yield (k, v)
    return dict(inner(d, key))


# Stats processing generators
#
# In general, these all take a stats iterable and yield individual
# stats dictionaries modified in some way. Unless specified otherwise,
# they should all be chainable.


def unknown_gen(stats, total_key, dyn_key, unknown_key='unknown'):
    """Calculate and record unknown counts for the breakdown in ``dyn_key``.

    Unknown is simply the difference between the total and sum of a breakdown.
    """
    # Using an object for the unknown key allows us to prevent key collisions
    # in the case where there is an existing key named ``unknown_key``, but the
    # value is not a scalar (ie a dict). This can occur with an UpdateCount
    # breakdown of applications. This object trick works because we know that
    # keys coming from the data store will always be strings.
    #
    # If scalar, we simply add in the unknown count. If not, use the object
    # as the key. Once results are flattened, the object resolves to the same
    # string as specified in ``unknown_key``. We end up with something like:
    #
    # {'total_key': 3, 'dyn_key/unknown/a': 2, 'dyn_key/unknown': 1}
    for s in stats:
        uk_sum = max(0, s[total_key] - s[dyn_key].sum_reduce())

        val = s[dyn_key].get(unknown_key, 0)
        if isinstance(val, dict):
            # Create a new entry with an object key since the normal
            # case below would result in a TypeError from: scalar + dict
            s[dyn_key][DictKey(unknown_key)] = uk_sum
        else:
            s[dyn_key][unknown_key] = uk_sum + val
        yield s


def quantize_gen(stats, keys=None, precision='0.01'):
    """Quantize Decimal values for the specified ``keys`` with ``precision``.

    ``keys`` should be a list. If not specified, all Decimal values will be
    quantized.

    Rounding behavior can be controlled via decimal.setcontext().
    """
    prec = Decimal(precision)

    def inner(d, keys):
        for k, v in d.items():
            if keys is None or k in keys:
                if isinstance(v, Decimal):
                    yield (k, v.quantize(prec))
                elif isinstance(v, dict):
                    yield (k, StatsDict(inner(v, None)))
                else:
                    yield (k, v)
            else:
                yield (k, v)

    for s in stats:
        yield dict(inner(s, keys))


def decimal_to_int_gen(stats, keys=None):
    """Convert all Decimal values for the specified ``keys`` to integers.

    ``keys`` should be a list. If not specified, all Decimals will be
    converted.

    Rounding behavior can be controlled via decimal.setcontext().
    """
    prec = Decimal('1')

    def inner(d, keys):
        for k, v in d.items():
            if keys is None or k in keys:
                if isinstance(v, Decimal):
                    yield (k, int(v.quantize(prec)))
                elif isinstance(v, dict):
                    yield (k, StatsDict(inner(v, None)))
                else:
                    yield (k, v)
            else:
                yield (k, v)

    for s in stats:
        yield dict(inner(s, keys))


def flatten_gen(stats, flatten_key):
    """Generate stats with values flattened for ``flatten_key``."""
    for s in stats:
        yield flatten_dict(s, flatten_key)


def values_gen(stats, ordered_keys=[], zero_val=0):
    """Generate lists of values for keys specified in ``ordered_keys``.

    A ``zero_val`` value will be used for any stat where a key does not exist.

    Results from this generator are not chainable into other generic stats
    generators.
    """
    for s in stats:
        yield [s.get(k, zero_val) for k in ordered_keys]
