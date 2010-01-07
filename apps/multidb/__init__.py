"""
With :class:`~multidb.SlaveQuerySet` and :class:`~multidb.SlaveMixin`, all read
queries will go to a slave database; all inserts, updates, and deletes will do
to the ``default`` database.

First, define ``SLAVE_DATABASES`` in your settings.  It should be a list of
database aliases that can be found in ``DATABASES``::

    DATABASES = {
        'default': {...},
        'shadow-1': {...},
        'shadow-2': {...},
    }
    SLAVE_DATABASES = ['shadow-1', 'shadow-2']

Then add a :class:`multidb.SlaveManager` to your model and inherit from
:class:`multidb.SlaveMixin`::

    from django.db import models

    import multidb


    class Slurpee(multidb.SlaveMixin, models.Model):
        number = models.IntegerField()

        objects = multidb.SlaveManager()

Instead of a normal :class:`~django.db.models.query.QuerySet`, the
``SlaveManager`` will return a ``SlaveQuerySet`` that sends all traffic to one
of the slaves.

The slave databases will be chosen in round-robin fashion.
"""
import itertools
import random

from django.conf import settings
from django.db import models, DEFAULT_DB_ALIAS


if getattr(settings, 'SLAVE_DATABASES'):
    # Shuffle the list so the first slave db isn't slammed during startup.
    dbs = list(settings.SLAVE_DATABASES)
    random.shuffle(dbs)
    slaves = itertools.cycle(dbs)
else:
    slaves = itertools.repeat(DEFAULT_DB_ALIAS)


class SlaveManager(models.Manager):
    """Returns a SlaveQuerySet instead of a normal QuerySet."""

    def get_query_set(self):
        return SlaveQuerySet(self.model)


class SlaveQuerySet(models.query.QuerySet):
    """
    Sends SELECTs to one of the slave databases in a round-robin schedule.

    A specific database can be selected with the ``using`` statement.
    """

    @property
    def db(self):
        if self._db is None:
            self._db = slaves.next()
        return self._db


class SlaveMixin(object):
    """Sends all INSERTs, UPDATEs, and DELETEs to the default database."""

    def save(self, force_insert=False, force_update=False, using=None):
        using = using or DEFAULT_DB_ALIAS
        return super(SlaveMixin, self).save(force_insert, force_update, using)

    def delete(self, using=None):
        using = using or DEFAULT_DB_ALIAS
        return super(SlaveMixin, self).delete(using)
