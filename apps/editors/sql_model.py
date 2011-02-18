import copy
import re

from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.db import connection, models
from django.db.models import Q
from django.db.models.sql.query import AND, OR
from django.utils.tree import Node


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
        if 'limit' not in self.base_query:
            self.base_query['limit'] = []
        if '_args' not in self.base_query:
            self.base_query['_args'] = {}
        self._cursor = None
        self._record_set = []

    def __iter__(self):
        self._build_cursor()
        for row in self._iter_cursor_results():
            yield row

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
                # Get all rows!  Better to use a limit with slices.
                self._build_cursor()
                self._build_record_set()
            return self._record_set[key]
        else:
            raise TypeError('Key must be a slice or integer.')

    def all(self):
        return self._clone()

    def count(self):
        """Count of all results, preserving aggregate grouping."""
        self._execute('SELECT count(*) from (%s) as q' % self.as_sql())
        return self._cursor.fetchone()[0]

    def get(self):
        clone = self._clone()
        cnt = clone.count()
        if cnt > 1:
            raise clone.sql_model.MultipleObjectsReturned(
                'get() returned more than one row -- it returned %s!' % cnt)
        elif cnt == 0:
            raise clone.sql_model.DoesNotExist('No rows matching query')
        else:
            return clone[0:1][0]

    def exclude(self, *args, **kw):
        raise NotImplementedError()

    def filter(self, *args, **kw):
        """Adds a where clause with keyword args.

        Example::

            qs = qs.filter(category='trees')
            qs = qs.filter(Q(type=1) | Q(name='foo'))

        """
        clone = self._clone()
        for arg in args:
            if isinstance(arg, Q):
                clone.base_query['where'].append(
                                    '(%s)' % (clone._kw_clause_from_q(arg)))
            else:
                raise TypeError(
                        'non keyword args should be Q objects, got %r' % arg)
        for field, val in kw.items():
            clone.base_query['where'].append(clone._kw_filter_to_clause(field,
                                                                        val))
        return clone

    def filter_raw(self, *args):
        """Adds a where clause in limited SQL.

        Examples::

            qs = qs.filter_raw('total >', 1)
            qs = qs.filter_raw('total >=', 1)
            qs = qs.filter_raw(Q('name LIKE', '%foo%') |
                               Q('status IN', [1, 2, 3]))

        The field on the leftside can be a key in the select dictionary.
        That is, it will be replaced with the actual expression when the
        query is built.
        """
        clone = self._clone()
        specs = []
        for arg in args:
            if isinstance(arg, Q):
                clone.base_query['where'].append(
                                    '(%s)' % (clone._raw_clause_from_q(arg)))
            else:
                specs.append(arg)
        if len(specs):
            clone.base_query['where'].append(clone._filter_to_clause(*specs))
        return clone

    def having(self, spec, val):
        """Adds a having clause in limited SQL.

        Examples::

            qs = qs.having('total >', 1)
            qs = qs.having('total >=', 1)

        The field on the leftside can be a key in the select dictionary.
        That is, it will be replaced with the actual expression when the
        query is built.
        """
        clone = self._clone()
        clone.base_query['having'].append(clone._filter_to_clause(spec, val))
        return clone

    def as_sql(self):
        stmt = self._compile(self.base_query)
        return stmt

    def _clone(self):
        return self.__class__(self.sql_model,
                              base_query=copy.deepcopy(self.base_query))

    def _parse_q(self, q_object):
        """Returns a parsed Q object.

        eg. [([('product =', 'AND'), ('life jacket', 'AND')], 'OR'),
             ([('product =', 'AND'), ('defilbrilator', 'AND')], 'OR')]
        """
        specs = []
        # TODO(Kumar): construct NOT clause:
        if q_object.negated:
            raise NotImplementedError('negated Q objects')
        for child in q_object.children:
            connector = q_object.connector
            if isinstance(child, Node):
                sp = self._parse_q(child)
                specs.append((sp, connector))
            else:
                specs.append((child, connector))
        return specs

    def _raw_clause_from_q(self, q_object):
        parts = self._parse_q(q_object)
        clause = []
        # TODO(Kumar) this doesn't handle nesting!
        for part in parts:
            specs, connector = part
            # Remove the AND in each spec part:
            specs = [s[0] for s in specs]
            clause.extend([self._filter_to_clause(*specs),
                           connector])
        return u' '.join(clause[:-1]) # skip the last connector

    def _kw_clause_from_q(self, q_object):
        parts = self._parse_q(q_object)
        clause = []
        for part in parts:
            specs, connector = part
            clause.extend([self._kw_filter_to_clause(*specs),
                           connector])
        return u' '.join(clause[:-1]) # skip the last connector

    def _kw_filter_to_clause(self, field, val):
        if not FIELD_PATTERN.match(field):
            raise ValueError('Not a valid field for where clause: %r' % field)
        param_k = self._param(val)
        if field in self.base_query['select']:
            field = self.base_query['select'][field]
        return '%s = %%(%s)s' % (field, param_k)

    def _filter_to_clause(self, *specs):
        specs = list(specs)
        if (len(specs) % 2) != 0:
            raise TypeError(
                    "Expected pairs of 'spec =', 'val'. Got: %r" % specs)
        full_clause = []
        while len(specs):
            spec, val = specs.pop(0), specs.pop(0)
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
                # eg. WHERE foo IN (%(param_0)s, %(param_1)s, %(param_2)s)
                #     WHERE foo IN (1, 2, 3)
                parts = ['%(' + self._param(p) + ')s' for p in iter(val)]
                param = '(%s)' % ', '.join(parts)
            else:
                param = '%%(%s)s' % self._param(val)
            full_clause.append('%s %s %s' % (field, clause.group('op'), param))
        and_ = u' %s ' % AND
        c = and_.join(full_clause)
        if len(full_clause) > 1:
            # Protect OR clauses
            c = u'(%s)' % c
        return c

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
        clone = self._clone()
        clone.base_query['order_by'].append('%s %s' % (field, dir))
        return clone

    def _compile(self, parts):
        sep = ",\n"
        and_ = ' %s\n' % AND
        select = ['%s AS %s' % (v, k) for k, v in parts['select'].items()]
        stmt = "SELECT\n%s\nFROM\n%s" % (sep.join(select),
                                         "\n".join(parts['from']))
        if parts.get('where'):
            stmt = "%s\nWHERE\n%s" % (stmt, and_.join(parts['where']))
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
        self._cursor.execute(sql, self.base_query['_args'])

    def _param(self, val):
        param_k = 'param_%s' % len(self.base_query['_args'].keys())
        self.base_query['_args'][param_k] = val
        return param_k

    def _build_cursor(self):
        self._execute(self.as_sql())

    def _build_record_set(self):
        self._record_set = []
        for row in self._iter_cursor_results():
            self._record_set.append(row)

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
