import calendar
from datetime import date, timedelta
from decimal import Decimal, DivisionByZero

from django.db import models

import phpserialize as php
try:
    import simplejson as json
except ImportError:
    import json

import caching.base


# Common date helpers
# These all take a date or datetime and return a date.


def prev_month_period(d):
    """Determine the date range of the previous month."""
    yr, mo = divmod(d.year * 12 + d.month - 2, 12)
    return period_of_month(date(yr, mo + 1, 1))


def prev_week_period(d):
    """Determine the date range of the previous week."""
    return period_of_week(d - timedelta(7))


def prev_day_period(d):
    """Determine the date range of the previous day."""
    return period_of_day(d - timedelta(1))


def period_of_month(d):
    """Determine the month range for a date or datetime."""
    eom = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, 1), date(d.year, d.month, eom)


def period_of_week(d):
    """Determine the week range for a date or datetime."""
    ws = d - timedelta(d.weekday())
    we = ws + timedelta(6)
    return date(ws.year, ws.month, ws.day), date(we.year, we.month, we.day)


def period_of_day(d):
    """Determine the day range for a date or datetime."""
    return date(d.year, d.month, d.day), date(d.year, d.month, d.day)


class StatsAggregate(object):
    """Base class for StatsQuerySet aggregation. """

    def __init__(self, field_name):
        self.field_name = field_name

    def reset(self, zero_value):
        """Reset internal state based on the specified zero value."""
        pass

    def accumulate(self, value):
        """Accumulate calculation, called once per row/object."""
        pass

    def final_result(self, n_rows, n_days):
        """Return the final aggregate result.

        n_rows is the number of rows/objects in the aggregate period.
        n_days is the number of days in the aggregate period.
        """
        return None


class Count(StatsAggregate):
    """Counts the number of rows/objects in an aggregate period."""

    def __init__(self, field_name):
        super(Count, self).__init__(field_name)
        self.count = 0

    def reset(self, zero_value):
        self.count = 0

    def accumulate(self, value):
        self.count += 1

    def final_result(self, n_rows=None, n_days=None):
        return self.count


class Sum(StatsAggregate):
    """Sum a set of values in a queryset."""

    def __init__(self, field_name):
        super(Sum, self).__init__(field_name)
        self.sum = None

    def reset(self, zero_value):
        self.sum = zero_value

    def accumulate(self, value):
        try:
            self.sum = self.sum + value
        except TypeError:
            pass

    def final_result(self, n_rows=None, n_days=None):
        return self.sum


class First(StatsAggregate):
    """Returns the first value in a queryset."""

    def __init__(self, field_name):
        super(First, self).__init__(field_name)
        self.got_it = False
        self.value = None

    def reset(self, zero_value):
        self.got_it = False
        self.value = None

    def accumulate(self, value):
        if not self.got_it:
            self.value = value
            self.got_it = True

    def final_result(self, n_rows=None, n_days=None):
        return self.value


class Last(First):
    """Returns the last value in a queryset."""

    def accumulate(self, value):
        self.value = value
        self.got_it = True


class Avg(Sum):
    """Calculate an average per row/object."""

    def final_result(self, n_rows, n_days):
        try:
            return self.sum * (1 / Decimal(n_rows))
        except (TypeError, DivisionByZero):
            return None


class DayAvg(Sum):
    """Calculate an average per day."""

    def final_result(self, n_rows, n_days):
        try:
            return self.sum * (1 / Decimal(n_days))
        except (TypeError, DivisionByZero):
            return None


class StatsQuerySet(caching.base.CachingQuerySet):

    def __init__(self, *args, **kwargs):
        super(StatsQuerySet, self).__init__(*args, **kwargs)
        self._stats_date_field = kwargs['model'].stats_date_field

    def summary(self, *fields, **kwargs):
        """Summarizes the entire queryset.

        Arguments should be the names of summable fields found in the queryset.
        Fields may be renamed in the results by using named arguments:

        >>> qs.summary('swallows', dead_parrots='parrots')
        {'row_count': 1, 'start': None, 'end': None, 'swallows': 10,
         'dead_parrots': 7}
        """
        # Use some aggregate trickery in order to determine the date range
        # of the entire queryset. Other aggregates depend on knowing the
        # length of this range.
        kwargs.update({'_tricky_start': Last(self._stats_date_field),
                       '_tricky_end': First(self._stats_date_field)})

        # This is the normal prep/accumulate phase.
        fields = self._map_fields(*fields, **kwargs)
        summary = self.zero_summary(**fields)
        self._reset_aggregates(summary, **fields)
        for obj in self:
            self._accumulate_aggregates(obj, **fields)

        # Replace start/end with our computed First/Last values.
        summary[self._start_key] = fields['_tricky_start'].final_result()
        summary[self._end_key] = fields['_tricky_end'].final_result()

        # Now other aggregates will be able to use day count.
        self._finalize_aggregates(summary, **fields)

        # We don't need these anymore.
        del(summary['_tricky_start'])
        del(summary['_tricky_end'])

        return summary

    def period_summary(self, period, *fields, **kwargs):
        """Calls one of daily_summary, weekly_summary, or monthly_summary.

        Period must be 'day', 'week', or 'month'
        otherwise a KeyError is raised.
        """
        summaries = {'day': self.daily_summary, 'week': self.weekly_summary,
                     'month': self.monthly_summary}
        return summaries[period](*fields, **kwargs)

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
        [{'row_count': 1, 'start': date(2009, 5, 3), 'end': date(2009, 5, 3),
          'swallows': 0, 'dead_parrots': 2},
         {'row_count': 1, 'start': date(2009, 5, 2), 'end': date(2009, 5, 2),
          'swallows': 10, 'dead_parrots': 5}]
        """
        fill_holes = kwargs.pop('fill_holes', False)
        fields = self._map_fields(*fields, **kwargs)
        return self._summary_iter(fields, fill_holes=fill_holes)

    def weekly_summary(self, *fields, **kwargs):
        fill_holes = kwargs.pop('fill_holes', False)
        fields = self._map_fields(*fields, **kwargs)
        return self._summary_iter(fields, fill_holes=fill_holes,
            previous_period=prev_week_period, current_period=period_of_week)

    weekly_summary.__doc__ = daily_summary.__doc__

    def monthly_summary(self, *fields, **kwargs):
        fill_holes = kwargs.pop('fill_holes', False)
        fields = self._map_fields(*fields, **kwargs)
        return self._summary_iter(fields, fill_holes=fill_holes,
            previous_period=prev_month_period, current_period=period_of_month)

    monthly_summary.__doc__ = daily_summary.__doc__

    def zero_summary(self, **fields):
        """Returns a dictionary of 0 values for specified fields.

        >>> qs.zero_summary(date(2009, 1, 1), count_total='ignored')
        {'start': None, 'end': None, 'row_count': 0, 'count_total': 0}
        """

        res = {}
        for res_key, fname in fields.items():
            # handle special summary fields
            if fname in ('start', 'end'):
                res[res_key] = None
                continue

            # lookout for aggregates
            if isinstance(fname, StatsAggregate):
                fname = fname.field_name

            # zero-out value based on model field type
            field = self.model._meta.get_field_by_name(fname)[0]
            if isinstance(field, StatsDictField):
                # an empty summable dictionary
                res[res_key] = StatsDict()
            else:
                # everything else starts at 0 whether it can be summed or not
                res[res_key] = 0
        return res

    def _reset_aggregates(self, zero_sum, **fields):
        """Reset all aggregate fields.

        Call this prior to calculating results for a new period.
        """
        for k, f in fields.items():
            if isinstance(f, StatsAggregate):
                f.reset(zero_sum[k])

    def _accumulate_aggregates(self, obj, **fields):
        """Accumulate object falues for all aggregate fields."""
        for field in fields.values():
            if isinstance(field, StatsAggregate):
                field.accumulate(getattr(obj, field.field_name))

    def _finalize_aggregates(self, summary, **fields):
        """Record final aggregate results into summary.

        Call this after all rows/objects have been accumulated in a period.
        """
        # row and day counts
        # finalize row_count first
        summary[self._count_key] = fields[self._count_key].final_result()
        n_rows = summary[self._count_key]
        try:
            n_days = (summary[self._end_key] -
                      summary[self._start_key]).days + 1
        except (TypeError, AttributeError):
            n_days = 0

        # save final results
        for k, f in fields.items():
            if isinstance(f, StatsAggregate):
                summary[k] = f.final_result(n_rows, n_days)

    def _map_fields(self, *fields, **kwargs):
        """Make a map of result key names to model field names.

        Named arguments take precedence, for example:

        >>> qs._map_fields('a', 'b', c='cool', b='bee')
        {'start': 'start', 'end': 'end', 'row_count': 'row_count',
         'a': 'a', 'b': 'bee', 'c': 'cool'}
        """
        fields = dict(zip(fields, fields))
        fields.update(kwargs)

        # Our special fields are referenced frequently, so search for and save
        # their keys.
        self._start_key = self._end_key = self._count_key = None
        for k, field in fields.items():
            if field == 'start':
                self._start_key = k
            elif field == 'end':
                self._end_key = k
            elif field == 'row_count':
                self._count_key = k
                fields[k] = Count(self._stats_date_field)
            # Other non-aggregate fields are summed by default
            elif not isinstance(field, StatsAggregate):
                fields[k] = Sum(field)

        # the special fields 'start', 'end' and 'row_count' are implicit but
        # may be remapped
        if self._start_key is None:
            if 'start' in fields:
                raise KeyError("reserved field 'start' must be remapped")
            self._start_key = fields['start'] = 'start'

        if self._end_key is None:
            if 'end' in fields:
                raise KeyError("reserved field 'end' must be remapped")
            self._end_key = fields['end'] = 'end'

        if self._count_key is None:
            if 'row_count' in fields:
                raise KeyError("reserved field 'row_count' must be remapped")
            fields['row_count'] = Count(self._stats_date_field)
            self._count_key = 'row_count'

        return fields

    def _summary_iter(self, fields, fill_holes=False,
                      previous_period=prev_day_period,
                      current_period=period_of_day):
        """Generates generic date period summaries of fields in the queryset.

        The fields argument should be a dictionary that maps result keys
        to valid field names in the queryset.

        Arguments:
            fields
                A dictionary that maps keys to fieldnames (see _map_fields)

            fill_holes
                If True, create zero count summaries for periods in the
                middle of the queryset that contain no records.

            previous_period
                A function that calculates the range of the period
                before a date

            current_period
                A function that calculates the range of the period
                containing a date or datetime
        """
        summary_zero = self.zero_summary(**fields)
        summary = None

        for obj in self:
            start, end = current_period(getattr(obj, self._stats_date_field))

            if summary is None:
                # XXX: add option to fill in holes at end of timeseries?
                # prep first non-zero result
                summary = summary_zero.copy()
                summary[self._start_key] = start
                summary[self._end_key] = end
                self._reset_aggregates(summary, **fields)

            if summary[self._start_key] != start:
                self._finalize_aggregates(summary, **fields)
                yield summary

                # option: fill holes in middle of timeseries
                if fill_holes:
                    prev_start, prev_end = previous_period(
                        summary[self._start_key])
                    while prev_start > start:
                        filler = summary_zero.copy()
                        filler[self._start_key] = prev_start
                        filler[self._end_key] = prev_end
                        self._reset_aggregates(filler, **fields)
                        self._finalize_aggregates(filler, **fields)
                        yield filler
                        prev_start, prev_end = previous_period(prev_start)

                # prep next non-zero result
                summary = summary_zero.copy()
                summary[self._start_key] = start
                summary[self._end_key] = end
                self._reset_aggregates(summary, **fields)

            # accumulate
            self._accumulate_aggregates(obj, **fields)

        if summary:
            self._finalize_aggregates(summary, **fields)
            yield summary

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

        return StatsQuerySet(model=self.model).order_by(date_order)


class StatsDict(dict):

    def sum_reduce(self):
        """Reduce the dictionary to a single value by summing.

        Values in nested dictionaries are also summed.
        """
        return self._rdict_sum_reduce(self)

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

    @classmethod
    def _rdict_sum_reduce(cls, d):
        """Recursively sum all values in a dictionary."""
        s = 0
        for val in d.values():
            if isinstance(val, dict):
                s = s + cls._rdict_sum_reduce(val)
            else:
                s = s + val
        return s


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
        if value and value[0] in '[{':
            # JSON
            try:
                d = json.loads(value)
            except ValueError:
                d = None
        else:
            # phpserialize data
            try:
                if isinstance(value, unicode):
                    value = value.encode('utf8')
                d = php.unserialize(value, decode_strings=True)
            except ValueError:
                d = None
        if isinstance(d, dict):
            return StatsDict(d)
        return None

    def get_db_prep_value(self, value):
        if value is None or value == '':
            return value
        try:
            value = json.dumps(dict(value))
        except TypeError:
            value = None
        return value

    def value_to_string(self, obj):
        return str(obj)
