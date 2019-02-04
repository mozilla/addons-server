import copy
import re

from django.core.exceptions import MultipleObjectsReturned, ObjectDoesNotExist
from django.db import connection
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
                # Translate slice into LIMIT, e.g.
                # [0:2] ->
                #          LIMIT 0, 2
                # [10:15] ->
                #          LIMIT 10, 5
                offset = self._check_limit(key.start)
                end = self._check_limit(key.stop)
                row_count = max(0, end - offset)
                self.base_query['limit'] = [offset, row_count]
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

    def __len__(self):
        return self.count()

    def all(self):
        return self._clone()

    def count(self):
        """Count of all results, preserving aggregate grouping."""
        self._execute('SELECT count(*) from (%s) as q' % self.as_sql())
        return self._cursor.fetchone()[0]

    def get(self, **kw):
        clone = self._clone()
        if kw:
            clone = clone.filter(**kw)
        cnt = clone.count()
        if cnt > 1:
            raise clone.sql_model.MultipleObjectsReturned(
                'get() returned more than one row -- it returned %s!' % cnt)
        elif cnt == 0:
            raise clone.sql_model.DoesNotExist(
                '%s matching query does not exist.' %
                self.sql_model.__class__.__name__)
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
                    '(%s)' % (clone._flatten_q(arg, clone._kw_clause_from_q)))
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
                    '(%s)' % (clone._flatten_q(arg, clone._filter_to_clause)))
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

    def latest(self, column):
        """Return the latest item, based on the given column."""

        clone = self._clone()
        clone.order_by('-%s' % column)
        if clone.count() == 0:
            raise clone.sql_model.DoesNotExist(
                '%s matching query does not exist.' %
                self.sql_model.__class__.__name__)
        return clone[0]

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
        clone.base_query['order_by'].append('%s %s' %
                                            (clone._resolve_alias(field), dir))
        return clone

    def as_sql(self):
        stmt = self._compile(self.base_query)
        return stmt

    def _clone(self):
        return self.__class__(self.sql_model,
                              base_query=copy.deepcopy(self.base_query))

    def _flatten_q(self, q_object, join_specs, stack=None):
        """Makes a WHERE clause out of a Q object (supports nested Q objects).

        Pass in join_specs(*specs) based on what kind of arguments you think
        the Q object will have.  filter() Qs are different from
        filter_raw() Qs.
        """
        specs = []
        if stack is None:
            stack = [None]
        # TODO(Kumar): construct NOT clause:
        if q_object.negated:
            raise NotImplementedError('negated Q objects')
        connector = q_object.connector

        def add(specs):
            c = join_specs(*specs, connector=connector)
            if stack[-1] in (AND, OR):
                c = u'(%s)' % (c)
            elif stack[-1] is not None:
                stack.append(connector)
            if c:
                stack.append(c)

        for child in q_object.children:
            if isinstance(child, Node):
                add(specs)
                specs[:] = []
                self._flatten_q(child, join_specs, stack=stack)
            else:
                specs.append(child)
        if len(specs):
            add(specs)
        return u' '.join([c for c in stack if c])

    def _kw_clause_from_q(self, *pairs, **kw):
        """Makes a WHERE clause out of pairs of (key, val) from Q objects."""
        connector = kw.get('connector', AND)
        stmt = []
        for field, val in pairs:
            stmt.append(self._kw_filter_to_clause(field, val))
        return (u' %s ' % connector).join(stmt)

    def _kw_filter_to_clause(self, field, val):
        """Makes a WHERE clause out of field = val."""
        if not FIELD_PATTERN.match(field):
            raise ValueError('Not a valid field for where clause: %r' % field)
        field = self._resolve_alias(field)
        if val is None:
            return u'%s IS NULL' % (field, )
        else:
            param_k = self._param(val)
            return u'%s = %%(%s)s' % (field, param_k)

    def _filter_to_clause(self, *specs, **kw):
        """Makes a WHERE clause out of filter_raw() arguments."""
        connector = kw.get('connector', AND)
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
            field = self._resolve_alias(field)
            if clause.group('op').lower() == 'in':
                # eg. WHERE foo IN (%(param_0)s, %(param_1)s, %(param_2)s)
                #     WHERE foo IN (1, 2, 3)
                parts = ['%(' + self._param(p) + ')s' for p in iter(val)]
                param = '(%s)' % ', '.join(parts)
            else:
                param = '%%(%s)s' % self._param(val)
            full_clause.append('%s %s %s' % (field, clause.group('op'), param))
        c = (u' %s ' % connector).join(full_clause)
        if len(full_clause) > 1:
            # Protect OR clauses
            c = u'(%s)' % c
        return c

    def _resolve_alias(self, field):
        """Access a field (or expression) by alias, similar to how a view works.
        """
        if field in self.base_query['select']:
            field = self.base_query['select'][field]
        return field

    def _compile(self, parts):
        sep = u",\n"
        and_ = u' %s\n' % AND
        select = [u'%s AS `%s`' % (v, k) for k, v in parts['select'].items()]
        stmt = u"SELECT\n%s\nFROM\n%s" % (sep.join(select),
                                          u"\n".join(parts['from']))
        if parts.get('where'):
            stmt = u"%s\nWHERE\n%s" % (stmt, and_.join(parts['where']))
        if parts.get('group_by'):
            stmt = u"%s\nGROUP BY\n%s" % (stmt, parts['group_by'])
        if parts.get('having'):
            stmt = u"%s\nHAVING\n%s" % (stmt, and_.join(parts['having']))
        if parts.get('order_by'):
            stmt = u"%s\nORDER BY\n%s" % (stmt, sep.join(parts['order_by']))
        if len(parts['limit']):
            stmt = u"%s\nLIMIT %s" % (stmt, ', '.join([str(i) for i in
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

    # django-tables2 looks for this to decide what Columns to add.
    class _meta(object):
        fields = []

    class DoesNotExist(ObjectDoesNotExist):
        pass

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

        Example::

            def base_query(self):
                return {
                    'select': {
                        'category': 'c.name',
                        'total': 'count(*)',
                        'latest_product_date': 'max(p.created)'
                    },
                    'from': [
                        'product p',
                        'join product_cat x on x.product_id=p.id',
                        'join category c on x.category_id=c.id'],
                    'where': [],
                    'group_by': 'category',
                    'having': []
                }
        """
        return {}

    def _explode_concat(self, value, sep=',', cast=int):
        """Returns list of IDs in a MySQL GROUP_CONCAT(field) result."""
        if value is None:
            # for NULL fields, ala left joins
            return []
        # Cope with a value like ...1261530,1261530, which occurs because of:
        # 1 line(s) were cut by GROUP_CONCAT()
        return [cast(i) for i in value.split(sep) if i]
