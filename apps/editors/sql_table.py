from django.core.exceptions import FieldError
from django.utils.datastructures import SortedDict

from django_tables.base import BaseTable, Rows, TableOptions


__all__ = ('SQLTable',)


class SQLTableOptions(TableOptions):
    def __init__(self, options=None):
        super(SQLTableOptions, self).__init__(options)
        self.columns = getattr(options, 'columns', None)
        # Exclude is not currently supported:
        self.exclude = getattr(options, 'exclude', None)


class SQLRows(Rows):

    def __init__(self, *args, **kwargs):
        super(SQLRows, self).__init__(*args, **kwargs)

    def _reset(self):
        self._length = None

    def __len__(self):
        """Use the queryset count() method to get the length, instead of
        loading all results into memory. This allows, for example,
        smart paginators that use len() to perform better.
        """
        if getattr(self, '_length', None) is None:
            self._length = self.table.data.count()
        return self._length

    # for compatibility with QuerySetPaginator
    count = __len__


class SQLTable(BaseTable):
    rows_class = SQLRows

    def __init__(self, data=None, *args, **kwargs):
        if data is None:
            raise ValueError("Table must be instantiated with data=queryset")
        else:
            self.queryset = data
        super(SQLTable, self).__init__(self.queryset, *args, **kwargs)

    def _validate_column_name(self, name, purpose):
        # Kind of overkill to ensure that the column is in the
        # query cursor. You'll get an error, don't worry.
        return True

    def _build_snapshot(self):
        """Overridden. The snapshot in this case is simply a queryset
        with the necessary filters etc. attached.
        """
        # reset caches
        self._columns._reset()
        self._rows._reset()
        qs = self.queryset
        if self.order_by:
            actual_order_by = self._resolve_sort_directions(self.order_by)
            qs = qs.order_by(*self._cols_to_fields(actual_order_by))
        return qs
