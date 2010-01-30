.. _caching:

=============
Cache Machine
=============

.. automodule:: caching.base


Classes that May Interest You
-----------------------------

.. autoclass:: caching.base.CacheMachine

.. autoclass:: caching.base.CachingManager
    :members:

    This :class:`manager <django.db.models.Manager>` always returns a
    :class:`~caching.CachingQuerySet`, and hooks up ``post_save`` and
    ``post_delete`` signals to invalidate caches.

.. autoclass:: caching.base.CachingMixin
    :members:

.. class:: caching.base.CachingQuerySet

    Overrides the default :class:`~django.db.models.QuerySet` to fetch objects
    from cache before hitting the database.
