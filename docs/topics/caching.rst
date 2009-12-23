.. _caching:

=============
Cache is King
=============

.. automodule:: caching

.. class:: caching.CachingManager

    This :class:`manager <django.db.models.Manager>` always returns a
    :class:`~caching.CachingQuerySet`, and hooks up ``post_save`` and
    ``post_delete`` signals to invalidate caches.

.. class:: caching.CachingQuerySet

    Overrides the default :class:`~django.db.models.QuerySet` to fetch objects
    from cache before hitting the database.
