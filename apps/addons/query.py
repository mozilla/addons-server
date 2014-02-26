from django.db import models
from django.db.models.sql import compiler

import caching.base as caching


class IndexQuerySet(caching.CachingQuerySet):

    def with_index(self, **kw):
        """
        Suggest indexes that should be used with this query as key-value pairs.

        qs.with_index(t1='xxx') => INNER JOIN t1 USE INDEX (`xxx`)
        """
        q = self._clone()
        if not isinstance(q.query, IndexQuery):
            q.query = self.query.clone(IndexQuery)
        q.query.index_map.update(kw)
        return q

    def fetch_missed(self, pks):
        # Remove the indexes before doing the id query.
        if hasattr(self.query, 'index_map'):
            index_map = self.query.index_map
            self.query.index_map = {}
            rv = super(IndexQuerySet, self).fetch_missed(pks)
            self.query.index_map = index_map
            return rv
        else:
            return super(IndexQuerySet, self).fetch_missed(pks)


class IndexQuery(models.query.sql.Query):
    """
    Extends sql.Query to make it possible to specify indexes to use.
    """

    def clone(self, klass=None, **kwargs):
        # Maintain index_map across clones.
        c = super(IndexQuery, self).clone(klass, **kwargs)
        c.index_map = dict(self.index_map)
        return c

    def get_compiler(self, using=None, connection=None):
        # Call super to figure out using and connection.
        c = super(IndexQuery, self).get_compiler(using, connection)
        return IndexCompiler(self, c.connection, c.using)

    def _setup_query(self):
        if not hasattr(self, 'index_map'):
            self.index_map = {}

    def get_count(self, using):
        # Don't use the index for counts, it's slower.
        index_map = self.index_map
        self.index_map = {}
        count = super(IndexQuery, self).get_count(using)
        self.index_map = index_map
        return count


class IndexCompiler(compiler.SQLCompiler):

    def get_from_clause(self):
        """
        Returns a list of strings that are joined together to go after the
        "FROM" part of the query, as well as a list any extra parameters that
        need to be included. Sub-classes, can override this to create a
        from-clause via a "select".

        This should only be called after any SQL construction methods that
        might change the tables we need. This means the select columns and
        ordering must be done first.
        """
        result = []
        qn = self.quote_name_unless_alias
        qn2 = self.connection.ops.quote_name
        index_map = self.query.index_map
        first = True
        from_params = []
        for alias in self.query.tables:
            if not self.query.alias_refcount[alias]:
                continue
            try:
                name, alias, join_type, lhs, join_cols, _, join_field = self.query.alias_map[alias]
            except KeyError:
                # Extra tables can end up in self.tables, but not in the
                # alias_map if they aren't in a join. That's OK. We skip them.
                continue
            alias_str = (alias != name and ' %s' % alias or '')
            ### jbalogh wuz here. ###
            if name in index_map:
                use_index = 'USE INDEX (%s)' % qn(index_map[name])
            else:
                use_index = ''
            if join_type and not first:
                extra_cond = join_field.get_extra_restriction(
                    self.query.where_class, alias, lhs)
                if extra_cond:
                    extra_sql, extra_params = extra_cond.as_sql(
                        qn, self.connection)
                    extra_sql = 'AND (%s)' % extra_sql
                    from_params.extend(extra_params)
                else:
                    extra_sql = ""
                result.append('%s %s%s %s ON ('
                              % (join_type, qn(name), alias_str, use_index))
                for index, (lhs_col, rhs_col) in enumerate(join_cols):
                    if index != 0:
                        result.append(' AND ')
                    result.append('%s.%s = %s.%s' %
                    (qn(lhs), qn2(lhs_col), qn(alias), qn2(rhs_col)))
                result.append('%s)' % extra_sql)
            else:
                connector = connector = '' if first else ', '
                result.append('%s%s%s %s' % (connector, qn(name), alias_str, use_index))
            ### jbalogh out. ###
            first = False
        for t in self.query.extra_tables:
            alias, unused = self.query.table_alias(t)
            # Only add the alias if it's not already present (the table_alias()
            # calls increments the refcount, so an alias refcount of one means
            # this is the only reference.
            if alias not in self.query.alias_map or self.query.alias_refcount[alias] == 1:
                connector = not first and ', ' or ''
                result.append('%s%s' % (connector, qn(alias)))
                first = False
        return result, from_params
