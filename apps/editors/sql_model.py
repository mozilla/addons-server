import copy
import re

from django.db import connection, models
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned


ORDER_PATTERN = re.compile(r'^[-+]?[a-zA-Z0-9_]+$')
FIELD_PATTERN = re.compile(r'^[a-zA-Z0-9_\.]+$')
RAW_FILTER_PATTERN = re.compile(
    r'^(?P<field>[a-zA-Z0-9_\.]+)\s*(?P<op>=|>|<|>=|<=|!=|IN|LIKE|ILIKE)\s*$',
    re.I)


class LazyRawSQLManager(object):
    """A deferred manager to work around metaclass lameness."""

    def __init__(self, sql_model_class):
        self.__sql_model_class = sql_model_class
        self.__manager = None

    def __getattr__(self, name):
        if not self.__manager:
            self.__manager = RawSQLManager(self.__sql_model_class())
        return getattr(self.__manager, name)


class RawSQLManager(object):
    """Raw SQL Manager for a Raw SQL Model.

    This provides a very minimal set of features in the Query Set API.
    """

    def __init__(self, sql_model, base_query=None):
        self.sql_model = sql_model
        if not base_query:
            base_query = copy.deepcopy(sql_model.base_query())
        self.base_query = base_query
        if 'where' not in self.base_query:
            self.base_query['where'] = []
        if 'having' not in self.base_query:
            self.base_query['having'] = []
        if 'order_by' not in self.base_query:
            self.base_query['order_by'] = []
        self.base_query['limit'] = []
        self._cursor = None
        self._args = {}
        self._record_set = []

    def all(self):
        return self.__class__(self.sql_model,
                              base_query=copy.deepcopy(self.base_query))

    def get(self):
        rows = list(self)
        cnt = len(rows)
        if cnt > 1:
            raise self.sql_model.MultipleObjectsReturned(
                'get() returned more than one row -- it returned %s!' % cnt)
        elif cnt == 0:
            raise self.sql_model.DoesNotExist('No rows matching query')
        else:
            return rows[0]

    def as_sql(self):
        stmt = self._compile(self.base_query)
        return stmt

    def count(self):
        """Count of all results, preserving aggregate grouping."""
        self._execute('SELECT count(*) from (%s) as q' % self.as_sql())
        return self._cursor.fetchone()[0]

    def filter(self, **kw):
        """Adds a where clause with keyword args.

        Example::

            qs = qs.filter(category='trees')

        """
        # NOTE: or is not supported, i.e. no Q objects
        for field, val in kw.items():
            if not FIELD_PATTERN.match(field):
                raise ValueError(
                    'Not a valid field for where clause: %r' % field)
            param_k = self._param(val)
            if field in self.base_query['select']:
                field = self.base_query['select'][field]
            self.base_query['where'].append('%s = %%(%s)s' % (field, param_k))
        return self

    def filter_raw(self, spec, val):
        """Adds a where clause in limited SQL.

        Examples::

            qs = qs.where('total >', 1)
            qs = qs.where('total >=', 1)

        The field on the leftside can be a key in the select dictionary.
        That is, it will be replaced with the actual expression when the
        query is built.
        """
        self.base_query['where'].append(self._filter_to_clause(spec, val))
        return self

    def having(self, spec, val):
        """Adds a having clause in limited SQL.

        Examples::

            qs = qs.having('total >', 1)
            qs = qs.having('total >=', 1)

        The field on the leftside can be a key in the select dictionary.
        That is, it will be replaced with the actual expression when the
        query is built.
        """
        self.base_query['having'].append(self._filter_to_clause(spec, val))
        return self

    def _filter_to_clause(self, spec, val):
        clause = RAW_FILTER_PATTERN.match(spec)
        if not clause:
            raise ValueError(
                'This is not a valid clause: %r; must match: %s' % (
                                            spec, RAW_FILTER_PATTERN.pattern))
        field = clause.group('field')
        if field in self.base_query['select']:
            # Support filtering by alias, similar to how a view works
            field = self.base_query['select'][field]
        if clause.group('op').lower() == 'in':
            # eg. WHERE foo IN (1, 2, 3)
            parts = ['%%(%s)s' % self._param(p) for p in iter(val)]
            param = '(%s)' % ', '.join(parts)
        else:
            param = '%%(%s)s' % self._param(val)
        return '%s %s %s' % (field, clause.group('op'), param)

    def order_by(self, spec):
        """Order by column (ascending) or -column (descending)."""
        if not ORDER_PATTERN.match(spec):
            raise ValueError('Invalid order by value: %r' % spec)
        if spec.startswith('-'):
            dir = 'DESC'
            field = spec[1:]
        else:
            dir = 'ASC'
            field = spec
        self.base_query['order_by'].append('%s %s' % (field, dir))
        return self

    def _compile(self, parts):
        sep = ",\n"
        select = ['%s AS %s' % (v, k) for k, v in parts['select'].items()]
        stmt = "SELECT\n%s\nFROM\n%s" % (sep.join(select),
                                         "\n".join(parts['from']))
        if parts.get('where'):
            stmt = "%s\nWHERE\n%s" % (stmt,
                                      " AND\n".join(parts['where']))
        if parts.get('group_by'):
            stmt = "%s\nGROUP BY\n%s" % (stmt, parts['group_by'])
        if parts.get('having'):
            stmt = "%s\nHAVING\n%s" % (stmt, sep.join(parts['having']))
        if parts.get('order_by'):
            stmt = "%s\nORDER BY\n%s" % (stmt, sep.join(parts['order_by']))
        if len(parts['limit']):
            stmt = "%s\nLIMIT %s" % (stmt, ', '.join([str(i) for i in
                                                      parts['limit']]))
        return stmt

    def _execute(self, sql):
        self._record_set = []
        self._cursor = connection.cursor()
        self._cursor.execute(sql, self._args)

    def _param(self, val):
        param_k = 'param_%s' % len(self._args.keys())
        self._args[param_k] = val
        return param_k

    def _build_cursor(self):
        self._execute(self.as_sql())

    def _build_record_set(self):
        self._record_set = []
        for row in self._iter_cursor_results():
            self._record_set.append(row)

    def __iter__(self):
        self._build_cursor()
        for row in self._iter_cursor_results():
            yield row

    def _iter_cursor_results(self):
        col_names = [c[0] for c in self._cursor.description]
        while 1:
            row = self._cursor.fetchone()
            if row is None:
                break
            yield self._make_row(row, col_names)

    def _make_row(self, row, col_names):
        values = dict(zip(col_names, row))
        return self.sql_model.__class__(**values)

    def _check_limit(self, i):
        i = int(i)
        if i < 0:
            raise IndexError("Negative indexing is not supported")
        return i

    def __getitem__(self, key):
        if isinstance(key, slice):
            if key.start and key.stop:
                self.base_query['limit'] = [self._check_limit(key.start),
                                            self._check_limit(key.stop)]
            elif key.start:
                self.base_query['limit'] = [self._check_limit(key.start)]
            elif key.stop:
                self.base_query['limit'] = [0, self._check_limit(key.stop)]
            self._build_cursor()
            self._build_record_set()
            return self._record_set
        elif isinstance(key, int):
            if not len(self._record_set):
                # Fetch just enough rows to get this one item:
                self.base_query['limit'] = [key + 1]
                self._build_cursor()
                self._build_record_set()
            return self._record_set[key]
        else:
            raise TypeError('Key must be a slice or integer.')


class RawSQLModelMeta(type):

    def __new__(cls, name, bases, attrs):
        super_new = super(RawSQLModelMeta, cls).__new__
        cls = super_new(cls, name, bases, attrs)
        cls.objects = LazyRawSQLManager(cls)
        return cls


class RawSQLModel(object):
    """Very minimal model-like object based on a SQL query.

    It supports barely enough for django-tables and the Django paginator.

    Why not use database views and Meta.managed=False?  Good question!
    This is for rare cases when you need the speed and optimization of
    building a query with many different types of where clauses.
    """
    __metaclass__ = RawSQLModelMeta
    DoesNotExist = ObjectDoesNotExist
    MultipleObjectsReturned = MultipleObjectsReturned

    def __init__(self, **kwargs):
        for key, val in kwargs.items():
            field = getattr(self.__class__, key, None)
            if field is None:
                raise TypeError(
                    'Field %r returned from raw SQL query does not have '
                    'a column defined in the model' % key)
            setattr(self, field.get_attname() or key, field.to_python(val))

    def base_query(self):
        """Returns a dict with parts of the raw SQL query.

        This method is called in a metaclass to create the manager
        as Model.objects.  Therefore you can't use super.
        """
        return {}

    def _explode_concat(self, value, sep=',', cast=int):
        """Returns list of IDs in a MySQL GROUP_CONCAT(field) result."""
        if value is None:
            # for NULL fields, ala left joins
            return []
        return [cast(i) for i in value.split(sep)]
