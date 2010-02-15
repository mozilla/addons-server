from datetime import date, timedelta
from decimal import Decimal

from django.db import models

import phpserialize as php

import caching.base


# Common date helpers
# These all take a date or datetime and return a date.


def prev_month(d):
    """Determine the start date of the previous month."""
    yr, mo = divmod(d.year * 12 + d.month - 2, 12)
    return date(yr, mo + 1, 1)


def prev_week(d):
    """Determine the start date of the previous week."""
    ws = d - timedelta(d.weekday() + 7)
    return date(ws.year, ws.month, ws.day)


def prev_day(d):
    """Determine the previous day."""
    pd = d - timedelta(1)
    return date(pd.year, pd.month, pd.day)


def start_of_month(d):
    """Determine the start of the month for a date or datetime."""
    return date(d.year, d.month, 1)


def start_of_week(d):
    """Determine the start of the week for a date or datetime."""
    ws = d - timedelta(d.weekday())
    return date(ws.year, ws.month, ws.day)


def start_of_day(d):
    """Determine the start of the day for a date or datetime."""
    return date(d.year, d.month, d.day)


class StatsQuerySet(caching.base.CachingQuerySet):

    def __init__(self, *args, **kwargs):
        super(StatsQuerySet, self).__init__(*args, **kwargs)
        self._stats_date_field = kwargs['model'].stats_date_field

    def summary(self, *fields, **kwargs):
        """Summarizes the entire queryset.

        Arguments should be the names of summable fields found in the queryset.
        Fields may be renamed in the results by using named arguments:

        >>> qs.summary('swallows', dead_parrots='parrots')
        {'row_count': 1, 'start': None, 'swallows': 10, 'dead_parrots': 7}
        """

        fields = self._map_fields(*fields, **kwargs)
        summary = self.zero_summary(None, **fields)
        for obj in self:
            summary = self._accumulate(obj, summary, **fields)

        return summary

    def daily_summary(self, *fields, **kwargs):
        """Generate daily/weekly/monthly summaries on the queryset.

        The queryset must be in reverse chronological order.

        Recognized keyword arguments:
            fill_holes
                If True, create zero count summaries for periods in the
                middle of the queryset that contain no records

        All other arguments should be the names of summable fields found
        in the queryset. Fields may be renamed in the results by using
        named arguments, for example:

        >>> [s for s in q.daily_summary('swallows', dead_parrots='parrots')]
        [{'row_count': 1, 'start': date(2009, 5, 3), 'swallows': 0,
          'dead_parrots': 2},
         {'row_count': 1, 'start': date(2009, 5, 2), 'swallows': 10,
          'dead_parrots': 5}]
        """
        fill_holes = kwargs.pop('fill_holes', False)
        fields = self._map_fields(*fields, **kwargs)
        return self._summary_iter(fields, fill_holes=fill_holes)

    def weekly_summary(self, *fields, **kwargs):
        fill_holes = kwargs.pop('fill_holes', False)
        fields = self._map_fields(*fields, **kwargs)
        return self._summary_iter(fields, fill_holes=fill_holes,
            previous_date=prev_week, format_date=start_of_week)

    weekly_summary.__doc__ = daily_summary.__doc__

    def monthly_summary(self, *fields, **kwargs):
        fill_holes = kwargs.pop('fill_holes', False)
        fields = self._map_fields(*fields, **kwargs)
        return self._summary_iter(fields, fill_holes=fill_holes,
            previous_date=prev_month, format_date=start_of_month)

    monthly_summary.__doc__ = daily_summary.__doc__

    def zero_summary(self, start_date, **fields):
        """Returns a dictionary of 0 values for specified fields.

        >>> qs.zero_summary(date(2009, 1, 1), count_total='ignored')
        {'start': date(2009, 1, 1), 'row_count': 0, 'count_total': 0}
        """

        res = {}
        for res_key, fname in fields.items():
            # handle special summary fields
            if fname == 'start':
                res[res_key] = start_date
                continue
            elif fname == 'row_count':
                res[res_key] = 0
                continue

            # handle regular model fields
            field = self.model._meta.get_field_by_name(fname)[0]
            if isinstance(field, StatsDictField):
                # an empty summable dictionary
                res[res_key] = StatsDict()
            else:
                # everything else starts at 0 whether it can be summed or not
                res[res_key] = 0
        return res

    def _accumulate(self, obj, ac, **fields):
        """Accumulates (sums) field values of an object.

        Example:

        >>> ac = {'start': date(2009, 1, 1), 'row_count': 2, 'sum': 10}
        >>> someobj.count = 4
        >>> qs._accumulate(someobj, ac, sum='count')
        {'start': date(2009, 1, 1), 'row_count': 3, 'count_sum': 14}
        """
        for ac_key, field in fields.items():
            # handle special summary fields
            if field == 'row_count':
                ac[ac_key] += 1
                continue
            elif field == 'start':
                continue

            # handle regular model fields
            try:
                # works with numbers and StatsDict
                ac[ac_key] = ac[ac_key] + getattr(obj, field)
            except TypeError:
                # anything else will keep the initial value (probably 0)
                pass
        return ac

    def _map_fields(self, *fields, **kwargs):
        """Make a map of result key names to model field names.

        Named arguments take precedence, for example:

        >>> qs._map_fields('a', 'b', 'c', c='cool', d='duh')
        {'a': 'a', 'b': 'b', 'c': 'cool', 'd': 'duh'}
        """
        fields = dict(zip(fields, fields))
        fields.update(kwargs)

        # the special fields 'start' and 'row_count' are implicit but
        # may be remapped
        if 'start' not in fields.values():
            if 'start' in fields:
                raise KeyError("reserved field 'start' must be remapped")
            fields['start'] = 'start'

        if 'row_count' not in fields.values():
            if 'row_count' in fields:
                raise KeyError("reserved field 'row_count' must be remapped")
            fields['row_count'] = 'row_count'

        return fields

    def _summary_iter(self, fields, fill_holes=False, previous_date=prev_day,
                      format_date=start_of_day):
        """Generates generic date period summaries of fields in the queryset.

        The fields argument should be a dictionary that maps result keys
        to valid field names in the queryset.

        Arguments:
            fields
                A dictionary that maps keys to fieldnames (see _map_fields)

            fill_holes
                If True, create zero count summaries for periods in the
                middle of the queryset that contain no records.

            previous_date
                A function that calculates the start of the next period
                prior to a date

            format_date
                A function that calculates the start of the period for
                a date or datetime
        """
        # we support remapping the special 'start' field - find it!
        start_key = [k for (k, v) in fields.items() if v == 'start'][0]

        ac_zero = self.zero_summary(None, **fields)
        ac = None

        for obj in self:
            d = format_date(getattr(obj, self._stats_date_field))

            if not ac:
                # XXX: add option to fill in holes at end of timeseries?
                # prep first non-zero result
                ac = ac_zero.copy()
                ac[start_key] = d

            if ac[start_key] != d:
                yield ac

                # option: fill holes in middle of timeseries
                if fill_holes:
                    nd = previous_date(ac[start_key])
                    while nd > d:
                        ac_fill = ac_zero.copy()
                        ac_fill[start_key] = nd
                        yield ac_fill
                        nd = previous_date(nd)

                # prep next non-zero result
                ac = ac_zero.copy()
                ac[start_key] = d

            # accumulate
            ac = self._accumulate(obj, ac, **fields)

        if ac:
            yield ac

        # XXX: add option to fill in holes at start of timeseries?
        return


class StatsManager(caching.base.CachingManager):

    def __init__(self, date_field='date'):
        super(StatsManager, self).__init__()
        self.date_field = date_field

    def contribute_to_class(self, cls, name):
        super(StatsManager, self).contribute_to_class(cls, name)

        # StatsQuerySet looks for our date field on the model
        cls.add_to_class('stats_date_field', self.date_field)

    def get_query_set(self):
        # The summary methods of StatsQuerySet require `date desc` ordering
        # so make that the default as a convenience.
        date_order = '-' + self.date_field

        # Filter out '0000-00-00' dates which are sadly valid in the
        # stats tables but mean nothing for analysis. '0000-00-00' is not
        # null and does not have a python equivalent, so we have to filter
        # using an inexact comparison.
        date_filter = {self.date_field + '__gt': date(1990, 1, 1)}

        return (StatsQuerySet(model=self.model)
                .filter(**date_filter).order_by(date_order))


class StatsDict(dict):

    def __add__(self, d):
        """Combines two dictionaries, summing values where keys overlap.

        Example:
            >>> a = StatsDict({'a': 1, 'b': 2})
            >>> b = StatsDict({'a': 1, 'c': 4})
            >>> a + b
            {'a': 2, 'b': 2, 'c': 4}
        """
        return StatsDict(self._rdict_sum(self, d))

    def __mul__(self, k):
        """Multiply all dictionary items by a constant value k.

        Example:
            >>> a = StatsDict({'a': 1, 'b': 2, 'c': {'d': 3}})
            >>> a * 3
            {'a': 3, 'b': 6, 'c': {'d': 9}}
        """
        if type(k) not in (int, float, Decimal):
            raise TypeError(
                "unsupported operand type(s) for *: '%s' and '%s'" % (
                    type(self).__name__, type(k).__name__))
        return StatsDict(self._rdict_mul(self, k))

    @classmethod
    def _rdict_mul(cls, d, k):
        """Recursively multiply dictionary items by a constant."""
        result = {}
        for key in d:
            if isinstance(d[key], dict):
                result[key] = cls._rdict_mul(d[key], k)
            else:
                result[key] = k * d[key]
        return result

    @classmethod
    def _rdict_sum(cls, a, b):
        """Recursively sum two dictionaries."""
        result = {}
        for k in set(a).union(b):
            a_val, b_val = (a.get(k, 0), b.get(k, 0))
            if isinstance(a_val, dict) and not isinstance(b_val, dict):
                b_val = {}
            elif isinstance(b_val, dict) and not isinstance(a_val, dict):
                a_val = {}
            if isinstance(a_val, dict):
                result[k] = cls._rdict_sum(a_val, b_val)
            else:
                result[k] = a_val + b_val
        return result


class StatsDictField(models.TextField):

    description = 'A dictionary of counts stored as serialized php.'
    __metaclass__ = models.SubfieldBase

    def db_type(self):
        return 'text'

    def to_python(self, value):
        # object case
        if value is None:
            return None
        if isinstance(value, dict):
            return StatsDict(value)

        # string case
        try:
            d = php.unserialize(value)
        except ValueError:
            d = None
        if isinstance(d, dict):
            return StatsDict(d)
        return None

    def get_db_prep_value(self, value):
        try:
            value = php.serialize(dict(value))
        except TypeError:
            value = None
        return value

    def value_to_string(self, obj):
        return str(obj)
